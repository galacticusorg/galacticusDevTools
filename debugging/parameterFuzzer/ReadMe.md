# Parameter fuzzer

Tools for fuzzing Galacticus' parameter space: generate many mutated parameter files from a known-good base file, run them, cluster the failures, reduce each to a minimal reproducer, and later re-measure those reproducers against changed code.

The first campaign (600 cases from `parameters/quickTest.xml`) found segmentation faults, classes which could not be constructed, runaway memory use, and a long list of unphysical values which ended in a floating point exception rather than a message naming the parameter. Those became pull requests #1527, #1530, #1533, #1538 and #1541.

All three scripts need `GALACTICUS_SOURCE_PATH` set to a Galacticus checkout, whose `python/` directory supplies the parameter catalog and validator.

## `fuzzParameters.py`

Generates and runs the campaign. Each case applies one to three random mutations to the base file:

* **scalar** — perturb a numeric, boolean or enumeration parameter (log-uniform rescaling, zero, sign flip, 1e30, 1e-30, declared bounds, and occasionally a value outside them);
* **addParameter** — insert a catalogued parameter the base file does not set;
* **swapImplementation** — switch a selector to another implementation of the same class, filling in any required parameters.

Every file is validated before it is run, and each run is given a timeout and an address-space cap, so that a runaway case fails quickly instead of taking the machine down. Failures are classified by signature — the fatal message and its location, or the first non-handler backtrace frame for a crash — and clustered in a report.

```
fuzzParameters.py --base parameters/quickTest.xml --catalog catalog.json \
                  --outdir fuzz --cases 600 --jobs 3 --seed 7 \
                  --timeout 60 --memory-limit 3 --exec ./Galacticus.exe
```

The catalog is built with `Galacticus.Parameters.catalog.build_catalog`, which records every functionClass, its implementations, and their parameters, types, defaults, enumerations and declared bounds.

## `minimizeCases.py`

Reduces every failing case to a minimal reproducer, by replaying each of its mutations alone against the base file, and then in pairs for anything still unresolved. A mutation which reproduces the same status — and, for a fatal error or crash, the same signature — is reported as the minimal reproducer, in `<outdir>/minimized.json`.

```
minimizeCases.py --base parameters/quickTest.xml --catalog catalog.json \
                 --outdir fuzz --exec ./Galacticus.exe --jobs 3
```

## `replayCases.py`

Rebuilds each minimized reproducer from the *current* base file and catalog and runs it again, so that a campaign's findings can be re-measured after the code has changed: which failures are fixed, which remain, and which changed their signature. Mutations which no longer apply — because the base file has moved on — are recorded as `notApplicable` rather than run.

```
replayCases.py --base parameters/quickTest.xml --catalog catalog.json \
               --minimized fuzz/minimized.json --outdir replay \
               --exec ./Galacticus.exe --jobs 4
```

## Notes

* **Point `GALACTICUS_DYNAMIC_DATA_PATH` at a scratch directory.** A case killed by the timeout while a table is being tabulated leaves a partial file in the dynamic data cache, after which every later run with those parameters fails with `dataset ... does not exist`. A scratch cache keeps that damage away from the real one and can be deleted afterwards.
* **Beware external tools.** A base file using `transferFunction=CAMB` re-runs CAMB for any mutation which changes the cosmology, which takes minutes rather than seconds; give such campaigns a much longer timeout. RecFast and CAMB also write their own "floating-point exceptions are signalling" notes, which the classifier counts as a crash.
* **A base file using XInclude must be resolved first**, with `Galacticus.Parameters.resolve.resolve_file`, since the mutators work on a single document.
