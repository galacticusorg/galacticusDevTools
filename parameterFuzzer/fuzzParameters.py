#!/usr/bin/env python3
"""Parameter-space fuzzer for Galacticus.

Starting from a known-good base parameter file, generate many mutated
parameter files using the parameter catalog (implementation swaps, numeric
perturbations to boundaries and extremes, enumeration swaps, boolean flips,
and insertion of catalogued parameters absent from the base file), validate
each file against the catalog, run it with a timeout, and cluster the failures
by error signature.

Usage:
    fuzzParameters.py --base parameters/quickTest.xml --catalog catalog.json \
                      --outdir fuzz --cases 200 --jobs 4 --seed 1 \
                      [--timeout SECONDS] [--exec Galacticus.exe] [--generate-only]

Every case lives in <outdir>/case-NNNN/ with parameters.xml, run.log, and a
JSON record. A summary is written to <outdir>/cases.json and <outdir>/report.md.

`GALACTICUS_SOURCE_PATH` must point at a Galacticus checkout, whose `python/`
directory supplies the parameter catalog and validator.

Andrew Benson (21-September-2026).
"""

import argparse
import collections
import concurrent.futures
import json
import math
import os
import random
import re
import resource
import shutil
import signal
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.join(os.environ.get('GALACTICUS_SOURCE_PATH', '.'), 'python'))
from Galacticus.Parameters.validate import _Index, validate_file  # noqa: E402

# Failure markers used by the test suite / CI to judge a run log.
FAILURE_MARKERS = ('FAIL', 'FAILED', 'fatal', 'aborted', 'ODE integration failed',
                   'unrecognized parameter')
CRASH_MARKERS = ('experienced a floating point exception', 'Program received signal',
                 'Segmentation fault', 'Floating-point exception', 'SIGFPE', 'SIGSEGV',
                 'Backtrace for this error', 'Program aborted')

# Selector element tags that are not functionClass selectors (component
# selections etc.) and are left alone.
SKIP_TAGS = {'formatVersion', 'lastModified', 'outputFileName'}


# ----------------------------------------------------------------------------
# Value helpers
# ----------------------------------------------------------------------------
def fortran_to_xml(value):
    """Convert a Fortran default literal into the form used in parameter files."""
    if value is None:
        return None
    text = str(value).strip()
    if text.lower() in ('.true.', 'true'):
        return 'true'
    if text.lower() in ('.false.', 'false'):
        return 'false'
    text = re.sub(r'([0-9.])[dD]([+-]?[0-9])', r'\1e\2', text)
    text = text.rstrip('dD') if re.match(r'^[+-]?[0-9.]+[dD]$', text) else text
    return text.strip('"').strip("'")


def to_float(text):
    try:
        return float(fortran_to_xml(text))
    except (TypeError, ValueError):
        return None


def to_int(text):
    try:
        return int(float(fortran_to_xml(text)))
    except (TypeError, ValueError):
        return None


def format_real(value):
    if value == 0.0:
        return '0.0'
    if abs(value) >= 1.0e-3 and abs(value) < 1.0e4:
        return f'{value:.6g}'
    return f'{value:.6e}'


def bound(constraints, which):
    if not constraints or which not in constraints:
        return None
    entry = constraints[which]
    value = to_float(entry.get('value'))
    if value is None:
        return None
    return value, bool(entry.get('inclusive', True))


def random_real(rng, parameter, current=None):
    """Generate a random real value for a parameter; returns (value, tactic)."""
    constraints = parameter.get('constraints') or {}
    reference = current if current is not None else to_float(parameter.get('default'))
    lower = bound(constraints, 'minimum')
    upper = bound(constraints, 'maximum')
    tactics = ['scale'] * 5 + ['zero', 'negative', 'huge', 'tiny']
    if lower:
        tactics += ['lowerBound'] * 2
    if upper:
        tactics += ['upperBound'] * 2
    if lower or upper:
        tactics += ['outsideBounds']
    tactic = rng.choice(tactics)
    value = None
    if tactic == 'scale':
        if reference is None or reference == 0.0:
            value = rng.uniform(-1.0, 1.0) if not lower else rng.uniform(0.0, 1.0)
        else:
            value = reference * 10.0 ** rng.uniform(-2.0, 2.0)
    elif tactic == 'zero':
        value = 0.0
    elif tactic == 'negative':
        value = -abs(reference) if reference else -1.0
    elif tactic == 'huge':
        value = 1.0e30
    elif tactic == 'tiny':
        value = 1.0e-30
    elif tactic == 'lowerBound':
        value = lower[0] if lower[1] else lower[0] + 1.0e-10 * max(1.0, abs(lower[0]))
    elif tactic == 'upperBound':
        value = upper[0] if upper[1] else upper[0] - 1.0e-10 * max(1.0, abs(upper[0]))
    elif tactic == 'outsideBounds':
        if lower and (not upper or rng.random() < 0.5):
            value = lower[0] - 1.0 - abs(lower[0])
        else:
            value = upper[0] + 1.0 + abs(upper[0])
    # Respect constraints unless the tactic is deliberately violating them.
    if tactic != 'outsideBounds':
        if lower and (value < lower[0] or (value == lower[0] and not lower[1])):
            value = lower[0] if lower[1] else lower[0] + 1.0e-10 * max(1.0, abs(lower[0]))
            tactic += '(clampedLower)'
        if upper and (value > upper[0] or (value == upper[0] and not upper[1])):
            value = upper[0] if upper[1] else upper[0] - 1.0e-10 * max(1.0, abs(upper[0]))
            tactic += '(clampedUpper)'
    return format_real(value), tactic


def random_integer(rng, parameter, current=None):
    constraints = parameter.get('constraints') or {}
    reference = current if current is not None else to_int(parameter.get('default'))
    lower = bound(constraints, 'minimum')
    upper = bound(constraints, 'maximum')
    tactics = ['scale'] * 4 + ['zero', 'one', 'negative', 'large']
    if lower:
        tactics += ['lowerBound']
    if upper:
        tactics += ['upperBound']
    tactic = rng.choice(tactics)
    if tactic == 'scale':
        value = int(round((reference if reference is not None else 1) * 10.0 ** rng.uniform(-1.0, 1.5)))
    elif tactic == 'zero':
        value = 0
    elif tactic == 'one':
        value = 1
    elif tactic == 'negative':
        value = -abs(reference) if reference else -1
    elif tactic == 'large':
        value = 1000000
    elif tactic == 'lowerBound':
        value = int(lower[0]) if lower[1] else int(lower[0]) + 1
    else:
        value = int(upper[0]) if upper[1] else int(upper[0]) - 1
    if tactic != 'outsideBounds':
        if lower and value < lower[0]:
            value = int(math.ceil(lower[0]))
            tactic += '(clampedLower)'
        if upper and value > upper[0]:
            value = int(math.floor(upper[0]))
            tactic += '(clampedUpper)'
    return str(value), tactic


def random_value(rng, index, parameter, current=None):
    """Return (value, tactic) for any scalar parameter, or (None, None) if the
    parameter cannot be sensibly fuzzed."""
    ptype = parameter.get('type')
    enumeration = parameter.get('enumeration')
    if enumeration and enumeration in index.enumerations:
        labels = [label for label in index.enumerations[enumeration] if label != current]
        if not labels:
            return None, None
        return rng.choice(labels), 'enumeration'
    if ptype == 'real':
        return random_real(rng, parameter, to_float(current) if current is not None else None)
    if ptype == 'integer':
        return random_integer(rng, parameter, to_int(current) if current is not None else None)
    if ptype == 'boolean':
        if current is not None:
            return ('false' if current.strip().lower() == 'true' else 'true'), 'flip'
        return rng.choice(['true', 'false']), 'boolean'
    return None, None


# ----------------------------------------------------------------------------
# Tree inspection
# ----------------------------------------------------------------------------
def iter_selectors(root, index):
    """Yield (element, base, label) for every functionClass selector element."""
    for element in root.iter():
        if element.tag in index.base_names and 'value' in element.attrib:
            yield element, element.tag, element.attrib['value']


def scalar_children(element, index, base, label):
    """Yield (child, parameterRecord) for scalar parameter children of a selector."""
    impl_type = index.type_by_base_label.get((base, label))
    if impl_type is None:
        return
    schema = index.schema(impl_type)
    for child in list(element):
        if child.tag in schema['scalars'] and 'value' in child.attrib:
            yield child, schema['scalars'][child.tag]


def fuzzable_scalars(root, index):
    """List every (element, parameter) pair for scalar parameters in the tree."""
    out = []
    for element, base, label in iter_selectors(root, index):
        for child, parameter in scalar_children(element, index, base, label):
            if parameter.get('type') in ('real', 'integer', 'boolean') or parameter.get('enumeration'):
                out.append((element, child, parameter))
    return out


def element_path(root, target):
    """Human-readable path to an element (tag[value]/tag[value]/...)."""
    parents = {child: parent for parent in root.iter() for child in parent}
    parts = []
    node = target
    while node is not None and node is not root:
        label = node.attrib.get('value')
        parts.append(f"{node.tag}[{label}]" if label else node.tag)
        node = parents.get(node)
    return '/'.join(reversed(parts))


# ----------------------------------------------------------------------------
# Mutations
# ----------------------------------------------------------------------------
def mutate_scalar(rng, root, index):
    candidates = fuzzable_scalars(root, index)
    if not candidates:
        return None
    parent, child, parameter = rng.choice(candidates)
    old = child.attrib['value']
    new, tactic = random_value(rng, index, parameter, old)
    if new is None or new == old:
        return None
    child.attrib['value'] = new
    return {'kind': 'scalar', 'tactic': tactic, 'path': element_path(root, child),
            'parameter': child.tag, 'old': old, 'new': new}


def mutate_add_parameter(rng, root, index):
    """Insert a catalogued scalar parameter that the base file does not set."""
    selectors = list(iter_selectors(root, index))
    rng.shuffle(selectors)
    for element, base, label in selectors:
        impl_type = index.type_by_base_label.get((base, label))
        if impl_type is None:
            continue
        schema = index.schema(impl_type)
        present = {child.tag for child in element}
        options = [p for name, p in schema['scalars'].items()
                   if name not in present and p.get('sourceElement') is None
                   and (p.get('type') in ('real', 'integer', 'boolean') or p.get('enumeration'))
                   and p.get('cardinality') in (None, '0..1', '1')]
        if not options:
            continue
        parameter = rng.choice(options)
        default = fortran_to_xml(parameter.get('default'))
        new, tactic = random_value(rng, index, parameter, default)
        if new is None:
            continue
        child = ET.SubElement(element, parameter['name'])
        child.attrib['value'] = new
        return {'kind': 'addParameter', 'tactic': tactic, 'path': element_path(root, child),
                'parameter': parameter['name'], 'old': default, 'new': new}
    return None


def required_parameters(index, impl_type):
    schema = index.schema(impl_type)
    return [p for name, p in schema['scalars'].items()
            if p.get('default') is None and p.get('sourceElement') is None
            and p.get('cardinality') in (None, '1')]


def mutate_swap_implementation(rng, root, index, allow_unfillable=False):
    """Replace one selector's implementation with a random alternative."""
    selectors = list(iter_selectors(root, index))
    rng.shuffle(selectors)
    for element, base, label in selectors:
        labels = sorted(index.labels_for(base) - {label})
        rng.shuffle(labels)
        for new_label in labels:
            impl_type = index.type_by_base_label.get((base, new_label))
            if impl_type is None:
                continue
            impl = index.implementations[impl_type]
            if not impl.get('constructorFound'):
                continue
            required = required_parameters(index, impl_type)
            # Only take implementations whose required parameters we can fill.
            fills = []
            ok = True
            for parameter in required:
                if parameter.get('type') in ('real', 'integer', 'boolean') or parameter.get('enumeration'):
                    value, tactic = random_value(rng, index, parameter, None)
                    if value is None:
                        ok = False
                        break
                    fills.append((parameter['name'], value, tactic))
                elif parameter.get('type') == 'string':
                    ok = False
                    break
                else:
                    ok = False
                    break
            if not ok and not allow_unfillable:
                continue
            # Perform the swap: drop old scalar children (keep sub-object
            # selectors, which the new implementation may still use).
            old_schema = index.schema(index.type_by_base_label.get((base, label), '')) \
                if (base, label) in index.type_by_base_label else {'scalars': {}}
            new_schema = index.schema(impl_type)
            for child in list(element):
                if child.tag in old_schema['scalars'] or child.tag not in index.base_names \
                        or child.tag not in new_schema['objects']:
                    element.remove(child)
            element.attrib['value'] = new_label
            for name, value, tactic in fills:
                ET.SubElement(element, name).attrib['value'] = value
            return {'kind': 'swapImplementation', 'path': element_path(root, element),
                    'class': base, 'old': label, 'new': new_label,
                    'filled': [{'parameter': n, 'value': v, 'tactic': t} for n, v, t in fills]}
    return None


MUTATORS = [
    (mutate_scalar, 5),
    (mutate_add_parameter, 2),
    (mutate_swap_implementation, 3),
]


def generate_case(rng, base_root, index, n_mutations):
    root = ET.fromstring(ET.tostring(base_root))
    mutations = []
    attempts = 0
    while len(mutations) < n_mutations and attempts < 20:
        attempts += 1
        mutator = rng.choices([m for m, _ in MUTATORS], weights=[w for _, w in MUTATORS])[0]
        result = mutator(rng, root, index)
        if result:
            mutations.append(result)
    return root, mutations


# ----------------------------------------------------------------------------
# Running and classifying
# ----------------------------------------------------------------------------
def first_user_frame(lines):
    """Return 'function (file:line)' for the first backtrace frame that is not
    the signal handler, the error module, or an anonymous frame."""
    for i, line in enumerate(lines):
        match = re.match(r'#\d+\s+0x[0-9a-f]+ in (\S+)', line)
        if not match:
            continue
        name = match.group(1)
        if '???' in name or 'error_MOD' in name or 'signal_handler' in name or name == 'main' or name == 'galacticus':
            continue
        location = ''
        if i + 1 < len(lines):
            at = re.match(r'\s*at (\S+):(\d+)', lines[i + 1])
            if at:
                location = f"{at.group(1).replace('./work/build/', '')}:{at.group(2)}"
        return f'{name} ({location})' if location else name
    return ''


def extract_signature(log):
    """Return (status, signature, message, location) from a run log."""
    lines = log.splitlines()
    lowered = log.lower()
    if 'allocate' in lowered and ('memory' in lowered or 'failed' in lowered) and 'fatal error' not in lowered:
        return 'memory', 'memory: allocation failure', 'allocation failure', ''
    crash_marker = next((m for m in CRASH_MARKERS if m.lower() in lowered), None)
    if crash_marker:
        frame = first_user_frame(lines)
        return 'crash', f'{crash_marker} @ {frame}', crash_marker, frame
    if 'Fatal error:' in log:
        start = next(i for i, line in enumerate(lines) if 'Fatal error:' in line)
        message_lines = []
        location = ''
        for line in lines[start + 1:]:
            if line.strip().startswith('Occurred at:'):
                continue
            if re.match(r'\s*(subroutine|function|module|file):', line):
                if line.strip().startswith('file:'):
                    location = line.strip()
                continue
            if line.strip().startswith('=>') or line.strip() == '':
                if message_lines:
                    break
                continue
            message_lines.append(line.strip())
        message = ' '.join(message_lines)
        normalized = re.sub(r'[-+]?\d[\d.]*(?:[eEdD][-+]?\d+)?', '#', message)
        normalized = re.sub(r'\s+', ' ', normalized)[:200]
        return 'fatal', f'{location} :: {normalized}', message, location
    return None, None, None, None


def run_case(case):
    """Run a single case; case is a dict with 'dir', 'exe', 'env', 'timeout'."""
    directory = case['dir']
    log_path = os.path.join(directory, 'run.log')
    started = time.time()
    memory_limit = int(case.get('memoryLimitGB', 3) * 1024 ** 3)

    def limit_resources():
        # Cap address space so a runaway allocation fails cleanly instead of
        # thrashing the whole machine; run in a new session so the process
        # group (including any spawned tools such as CAMB) can be killed.
        resource.setrlimit(resource.RLIMIT_AS, (memory_limit, memory_limit))

    with open(log_path, 'w') as log:
        process = subprocess.Popen([case['exe'], 'parameters.xml'], cwd=directory,
                                   env=case['env'], stdout=log, stderr=subprocess.STDOUT,
                                   preexec_fn=limit_resources, start_new_session=True)
        try:
            exit_code = process.wait(timeout=case['timeout'])
            timed_out = False
        except subprocess.TimeoutExpired:
            exit_code = None
            timed_out = True
        finally:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
    elapsed = time.time() - started
    with open(log_path, errors='replace') as log:
        text = log.read()
    status, signature, message, location = extract_signature(text)
    if timed_out:
        status, signature = 'timeout', 'timeout'
    elif status is None:
        unrecognized = sorted({re.sub(r'\s+', ' ', m.group(0))[:160]
                               for m in re.finditer(r'unrecognized parameter \[[^\]]*\]', text)})
        if 'ODE integration failed' in text or 'task failed' in text:
            status = 'odeFailure'
            codes = sorted({m.group(1) for m in re.finditer(r'ODE solver failed with error code (-?\d+)', text)})
            signature = f"odeFailure: exit {exit_code}, ODE error codes {','.join(codes) or '?'}"
        elif exit_code == 0 and unrecognized:
            status = 'unusedParameter'
            signature = 'unusedParameter: ' + '; '.join(unrecognized)
        elif exit_code == 0 and not any(marker in text for marker in FAILURE_MARKERS):
            status, signature = 'ok', 'ok'
        else:
            status = 'nonzero' if exit_code else 'markers'
            tail = [line for line in text.splitlines() if line.strip()][-1:] or ['']
            signature = f'{status}:{exit_code}:{tail[0][:120]}'
    warnings = sorted({line.strip()[:160] for line in text.splitlines() if 'WARNING' in line})
    # Remove the bulky HDF5 output; keep the log.
    for name in os.listdir(directory):
        if name.endswith('.hdf5'):
            os.remove(os.path.join(directory, name))
    return {'status': status, 'signature': signature, 'message': message, 'location': location,
            'exitCode': exit_code, 'elapsed': round(elapsed, 1), 'warnings': warnings}


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--base', required=True)
    parser.add_argument('--catalog', required=True)
    parser.add_argument('--outdir', required=True)
    parser.add_argument('--cases', type=int, default=100)
    parser.add_argument('--jobs', type=int, default=4)
    parser.add_argument('--seed', type=int, default=1)
    parser.add_argument('--timeout', type=float, default=60.0)
    parser.add_argument('--memory-limit', type=float, default=3.0, help='address-space cap per case, GB')
    parser.add_argument('--exec', dest='exe', default='Galacticus.exe')
    parser.add_argument('--max-mutations', type=int, default=3)
    parser.add_argument('--generate-only', action='store_true')
    parser.add_argument('--start', type=int, default=0, help='first case index (for appending runs)')
    args = parser.parse_args()

    catalog = json.load(open(args.catalog))
    index = _Index(catalog)
    base_tree = ET.parse(args.base)
    base_root = base_tree.getroot()
    os.makedirs(args.outdir, exist_ok=True)

    env = dict(os.environ)
    env['OMP_NUM_THREADS'] = '1'

    records = []
    for i in range(args.start, args.start + args.cases):
        rng = random.Random(args.seed * 1000003 + i)
        n_mutations = rng.randint(1, args.max_mutations)
        root, mutations = generate_case(rng, base_root, index, n_mutations)
        directory = os.path.join(args.outdir, f'case-{i:04d}')
        if os.path.isdir(directory):
            shutil.rmtree(directory)
        os.makedirs(directory)
        # Make the output land in the case directory.
        if root.find('outputFileName') is None:
            ET.SubElement(root, 'outputFileName').attrib['value'] = 'galacticus.hdf5'
        ET.indent(root, space='  ')
        parameters_path = os.path.join(directory, 'parameters.xml')
        ET.ElementTree(root).write(parameters_path, encoding='UTF-8', xml_declaration=True)
        findings, error = validate_file(parameters_path, catalog=catalog)
        record = {
            'case': i, 'dir': directory, 'mutations': mutations,
            'validation': {'error': error,
                           'findings': [f'{f.level}:{f.kind}:{f.path}:{f.message}' for f in findings]},
            'exe': args.exe, 'env': env, 'timeout': args.timeout, 'memoryLimitGB': args.memory_limit,
        }
        records.append(record)
    print(f'generated {len(records)} cases', flush=True)

    if not args.generate_only:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
            futures = {pool.submit(run_case, record): record for record in records}
            done = 0
            for future in concurrent.futures.as_completed(futures):
                record = futures[future]
                record['result'] = future.result()
                done += 1
                print(f"[{done}/{len(records)}] case {record['case']:04d}: "
                      f"{record['result']['status']} ({record['result']['elapsed']}s) "
                      f"{record['result']['signature'][:100]}", flush=True)

    for record in records:
        record.pop('env', None)
    with open(os.path.join(args.outdir, 'cases.json'), 'w') as handle:
        json.dump(records, handle, indent=1)
    if not args.generate_only:
        write_report(records, args)


def describe_mutation(mutation):
    if mutation['kind'] == 'swapImplementation':
        fills = ', '.join(f"{f['parameter']}={f['value']}" for f in mutation['filled'])
        return f"swap {mutation['class']}: {mutation['old']} -> {mutation['new']}" + (f" (with {fills})" if fills else '')
    return f"{mutation['kind']} {mutation['path']}: {mutation['old']} -> {mutation['new']} [{mutation['tactic']}]"


def write_report(records, args):
    by_status = collections.Counter(r['result']['status'] for r in records)
    clusters = collections.defaultdict(list)
    for record in records:
        if record['result']['status'] != 'ok':
            clusters[record['result']['signature']].append(record)
    lines = ['# Parameter fuzzing report', '',
             f"Base file: `{args.base}`; seed {args.seed}; {len(records)} cases; timeout {args.timeout}s.", '',
             '| Status | Count |', '|---|---|']
    for status, count in sorted(by_status.items()):
        lines.append(f'| {status} | {count} |')
    lines += ['', f'## Failure clusters ({len(clusters)})', '']
    for signature, members in sorted(clusters.items(), key=lambda kv: -len(kv[1])):
        example = members[0]
        lines.append(f'### {len(members)}x `{signature}`')
        lines.append('')
        if example['result'].get('message'):
            lines.append(f"Message: {example['result']['message']}")
            lines.append('')
        invalid = sum(1 for m in members if any(f.startswith('error') for f in m['validation']['findings']))
        lines.append(f"Validator flagged {invalid}/{len(members)} of these files as invalid before running.")
        lines.append('')
        for member in members[:5]:
            lines.append(f"- case {member['case']:04d} ({member['result']['elapsed']}s): " +
                         '; '.join(describe_mutation(m) for m in member['mutations']))
        lines.append('')
    with open(os.path.join(args.outdir, 'report.md'), 'w') as handle:
        handle.write('\n'.join(lines) + '\n')
    print('\n'.join(lines[:12]))


if __name__ == '__main__':
    main()
