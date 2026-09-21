#!/usr/bin/env python3
"""Minimize failing fuzz cases to single mutations.

For every non-ok case in <outdir>/cases.json (or the selected cases), replay
each recorded mutation alone on the base parameter file and re-run it. A
mutation that reproduces the same status (and, for fatal/crash, the same
signature) is reported as the minimal reproducer. If no single mutation
reproduces the failure, pairs are tried.

Usage:
    minimizeCases.py --base quickTest.xml --catalog catalog.json --outdir fuzz \
                     --exec Galacticus.exe [--jobs 3] [--cases 12,40,...]

Writes <outdir>/minimized.json and prints a summary.

Andrew Benson (21-September-2026).
"""

import argparse
import concurrent.futures
import itertools
import json
import os
import shutil
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fuzzParameters import run_case, required_parameters  # noqa: E402
from Galacticus.Parameters.validate import _Index  # noqa: E402


def find_by_path(root, path):
    """Locate an element from a 'tag[value]/tag[value]/...' path; the value in
    brackets is matched only where several siblings share the tag."""
    node = root
    for part in path.split('/'):
        tag, _, rest = part.partition('[')
        label = rest[:-1] if rest else None
        candidates = [child for child in node if child.tag == tag]
        if not candidates:
            return None
        if len(candidates) > 1 and label is not None:
            candidates = [c for c in candidates if c.attrib.get('value') == label] or candidates
        node = candidates[0]
    return node


def apply_mutation(root, mutation, index):
    kind = mutation['kind']
    if kind == 'scalar':
        parent_path, _, _ = mutation['path'].rpartition('/')
        parent = find_by_path(root, parent_path) if parent_path else root
        if parent is None:
            return False
        for child in parent:
            if child.tag == mutation['parameter'] and child.attrib.get('value') == mutation['old']:
                child.attrib['value'] = mutation['new']
                return True
        return False
    if kind == 'addParameter':
        parent_path, _, _ = mutation['path'].rpartition('/')
        parent = find_by_path(root, parent_path) if parent_path else root
        if parent is None:
            return False
        ET.SubElement(parent, mutation['parameter']).attrib['value'] = mutation['new']
        return True
    if kind == 'swapImplementation':
        # The recorded path names the implementation swapped *in*, which the base file does not contain, so the element is
        # located by the value it had. Matching the path as recorded silently failed for every such mutation.
        parent_path, _, last = mutation['path'].rpartition('/')
        parent  = find_by_path(root, parent_path) if parent_path else root
        tag     = last.partition('[')[0]
        element = None
        if parent is not None:
            for child in parent:
                if child.tag == tag and child.attrib.get('value') == mutation['old']:
                    element = child
                    break
        if element is None:
            return False
        base = mutation['class']
        old_type = index.type_by_base_label.get((base, mutation['old']))
        new_type = index.type_by_base_label.get((base, mutation['new']))
        old_schema = index.schema(old_type) if old_type else {'scalars': {}}
        new_schema = index.schema(new_type) if new_type else {'scalars': {}, 'objects': {}}
        for child in list(element):
            if child.tag in old_schema['scalars'] or child.tag not in index.base_names \
                    or child.tag not in new_schema['objects']:
                element.remove(child)
        element.attrib['value'] = mutation['new']
        for fill in mutation['filled']:
            ET.SubElement(element, fill['parameter']).attrib['value'] = fill['value']
        return True
    return False


def same_failure(original, result):
    if original['status'] != result['status']:
        return False
    if original['status'] in ('fatal', 'crash', 'unusedParameter', 'memory'):
        return original['signature'] == result['signature']
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', required=True)
    parser.add_argument('--catalog', required=True)
    parser.add_argument('--outdir', required=True)
    parser.add_argument('--exec', dest='exe', required=True)
    parser.add_argument('--jobs', type=int, default=3)
    parser.add_argument('--timeout', type=float, default=60.0)
    parser.add_argument('--memory-limit', type=float, default=3.0)
    parser.add_argument('--cases', default=None, help='comma-separated case numbers (default: all failing)')
    args = parser.parse_args()

    catalog = json.load(open(args.catalog))
    index = _Index(catalog)
    base_root = ET.parse(args.base).getroot()
    records = json.load(open(os.path.join(args.outdir, 'cases.json')))
    wanted = set(int(c) for c in args.cases.split(',')) if args.cases else None
    failing = [r for r in records if r.get('result', {}).get('status') not in (None, 'ok')
               and (wanted is None or r['case'] in wanted)]
    env = dict(os.environ)
    env['OMP_NUM_THREADS'] = '1'
    min_dir = os.path.join(args.outdir, 'minimized')
    os.makedirs(min_dir, exist_ok=True)

    def build(record, subset, tag):
        root = ET.fromstring(ET.tostring(base_root))
        for k in subset:
            if not apply_mutation(root, record['mutations'][k], index):
                return None
        if root.find('outputFileName') is None:
            ET.SubElement(root, 'outputFileName').attrib['value'] = 'galacticus.hdf5'
        directory = os.path.join(min_dir, f"case-{record['case']:04d}-{tag}")
        if os.path.isdir(directory):
            shutil.rmtree(directory)
        os.makedirs(directory)
        ET.indent(root, space='  ')
        ET.ElementTree(root).write(os.path.join(directory, 'parameters.xml'), encoding='UTF-8', xml_declaration=True)
        return {'dir': directory, 'exe': args.exe, 'env': env, 'timeout': args.timeout,
                'memoryLimitGB': args.memory_limit}

    # Stage 1: single mutations (skip cases that already have one mutation).
    jobs = []
    for record in failing:
        n = len(record['mutations'])
        if n == 1:
            record['minimal'] = {'mutations': [0], 'result': record['result'], 'dir': record['dir']}
            continue
        for k in range(n):
            case = build(record, [k], f'm{k}')
            if case:
                jobs.append((record, [k], case))
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = {pool.submit(run_case, case): (record, subset, case) for record, subset, case in jobs}
        for future in concurrent.futures.as_completed(futures):
            record, subset, case = futures[future]
            results.setdefault(record['case'], []).append((subset, future.result(), case['dir']))
    for record in failing:
        if 'minimal' in record:
            continue
        for subset, result, directory in sorted(results.get(record['case'], [])):
            if same_failure(record['result'], result):
                record['minimal'] = {'mutations': subset, 'result': result, 'dir': directory}
                break
    # Stage 2: pairs for anything unresolved.
    jobs = []
    for record in failing:
        if 'minimal' in record or len(record['mutations']) < 2:
            continue
        for pair in itertools.combinations(range(len(record['mutations'])), 2):
            case = build(record, list(pair), f"m{pair[0]}{pair[1]}")
            if case:
                jobs.append((record, list(pair), case))
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = {pool.submit(run_case, case): (record, subset, case) for record, subset, case in jobs}
        for future in concurrent.futures.as_completed(futures):
            record, subset, case = futures[future]
            results.setdefault(record['case'], []).append((subset, future.result(), case['dir']))
    for record in failing:
        if 'minimal' in record:
            continue
        for subset, result, directory in sorted(results.get(record['case'], [])):
            if same_failure(record['result'], result):
                record['minimal'] = {'mutations': subset, 'result': result, 'dir': directory}
                break
        if 'minimal' not in record:
            record['minimal'] = None

    out = [{'case': r['case'], 'status': r['result']['status'], 'signature': r['result']['signature'],
            'mutations': r['mutations'], 'minimal': r.get('minimal')} for r in failing]
    with open(os.path.join(args.outdir, 'minimized.json'), 'w') as handle:
        json.dump(out, handle, indent=1)
    resolved = sum(1 for r in out if r['minimal'])
    print(f'minimized {resolved}/{len(out)} failing cases')


if __name__ == '__main__':
    main()
