#!/usr/bin/env python3
"""Replay the minimal reproducer of every failing case of a fuzzing campaign.

Each case is rebuilt from the CURRENT base parameter file and catalog, then run
against a given executable, so that a campaign's findings can be re-measured
after the code (or the base file) has changed: which failures are fixed, which
remain, and which have changed their signature.

Usage:
    replayCases.py --base parameters/quickTest.xml --catalog catalog.json \
                   --minimized fuzz/minimized.json --outdir replay \
                   --exec Galacticus.exe [--jobs 4] [--timeout SECONDS] \
                   [--memory-limit GB] [--only-not-applicable replay/replay.json]

Cases whose mutations no longer apply -- because the base file changed -- are
recorded with the status `notApplicable` rather than run. Writes
<outdir>/replay.json: one record per case, carrying the status and signature it
had in the campaign alongside the result of the replay.

`GALACTICUS_SOURCE_PATH` must point at a Galacticus checkout, whose `python/`
directory supplies the parameter catalog and validator.

Andrew Benson (21-September-2026).
"""

import argparse
import concurrent.futures
import json
import os
import shutil
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fuzzParameters import run_case                                     # noqa: E402
from minimizeCases  import apply_mutation                               # noqa: E402

sys.path.insert(0, os.path.join(os.environ.get('GALACTICUS_SOURCE_PATH', '.'), 'python'))
from Galacticus.Parameters.validate import _Index                       # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base'     , required=True)
    parser.add_argument('--catalog'  , required=True)
    parser.add_argument('--minimized', required=True)
    parser.add_argument('--outdir'   , required=True)
    parser.add_argument('--exec'     , dest='exe', required=True)
    parser.add_argument('--jobs'              , type=int  , default=4  )
    parser.add_argument('--timeout'           , type=float, default=60.0)
    parser.add_argument('--memory-limit'      , type=float, default=3.0,
                        help='address-space cap per case, GB')
    parser.add_argument('--only-not-applicable', default=None,
                        help='a previous replay.json: replay only the cases it recorded as notApplicable')
    args = parser.parse_args()

    index   = _Index(json.load(open(args.catalog)))
    base    = ET.parse(args.base).getroot()
    records = json.load(open(args.minimized))
    if args.only_not_applicable:
        keep    = {e['case'] for e in json.load(open(args.only_not_applicable))
                   if e['result']['status'] == 'notApplicable'}
        records = [r for r in records if r['case'] in keep]
    environment                    = dict(os.environ)
    environment['OMP_NUM_THREADS'] = '1'
    os.makedirs(args.outdir, exist_ok=True)

    jobs, out = [], []
    for record in records:
        # Replay the minimal reproducer where one was found, and the whole mutation set otherwise.
        subset = record['minimal']['mutations'] if record['minimal'] else list(range(len(record['mutations'])))
        root   = ET.fromstring(ET.tostring(base))
        entry  = {
            'case'        : record['case'],
            'oldStatus'   : record['status'],
            'oldSignature': record['signature'],
            'minimal'     : bool(record['minimal']),
            'mutations'   : [record['mutations'][k] for k in subset],
        }
        out.append(entry)
        if not all(apply_mutation(root, record['mutations'][k], index) for k in subset):
            entry['result'] = {'status': 'notApplicable'}
            continue
        if root.find('outputFileName') is None:
            ET.SubElement(root, 'outputFileName').attrib['value'] = 'galacticus.hdf5'
        directory = os.path.join(args.outdir, f"case-{record['case']:04d}")
        shutil.rmtree(directory, ignore_errors=True)
        os.makedirs(directory)
        ET.indent(root, space='  ')
        ET.ElementTree(root).write(os.path.join(directory, 'parameters.xml'),
                                   encoding='UTF-8', xml_declaration=True)
        jobs.append((entry, {'dir': directory, 'exe': args.exe, 'env': environment,
                             'timeout': args.timeout, 'memoryLimitGB': args.memory_limit}))

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = {pool.submit(run_case, case): entry for entry, case in jobs}
        for future in concurrent.futures.as_completed(futures):
            futures[future]['result'] = future.result()

    with open(os.path.join(args.outdir, 'replay.json'), 'w') as handle:
        json.dump(out, handle, indent=1)
    changed = sum(1 for e in out if e['result']['status'] != e['oldStatus'])
    print(f"replayed {len(jobs)} of {len(out)} cases; {changed} changed status")


if __name__ == '__main__':
    main()
