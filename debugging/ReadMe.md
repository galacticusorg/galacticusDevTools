# Debugging, testing and profiling

Tools for finding, reducing and measuring problems in Galacticus: fuzzing, test-case reduction,
allocation profiling, comparison of analysis outputs, and micro-benchmarking.

### `parameterFuzzer/`

Fuzzes Galacticus' parameter space: generates many mutated parameter files from
a known-good base file, runs them, clusters the failures, reduces each to a
minimal reproducer, and later re-measures those reproducers against changed
code (`fuzzParameters.py`, `minimizeCases.py`, `replayCases.py`). The first
campaign, from `parameters/quickTest.xml`, found segmentation faults, a class
which could not be constructed, runaway memory use, and many unphysical values
which gave a floating point exception rather than a message naming the
parameter. See `parameterFuzzer/ReadMe.md` for usage and for the traps worth
knowing before starting a campaign.

### `deltaTestCaseReducer/`

Wrapper around the [Delta debugging tool](https://github.com/dsw/delta) for
reducing a Galacticus source file to a minimal example that still triggers a
specific error (a compiler bug, a runtime crash, etc.) by successively
removing lines. See `deltaTestCaseReducer/ReadMe.md` for usage and
`testScriptExample.sh` for an example test script. The `delta` source itself
is redistributed under its original BSD license; see
`deltaTestCaseReducer/License.txt`.

### `allocationProfiler/`

A lightweight `LD_PRELOAD` allocation profiler for finding which call sites drive
a program's heap-allocation churn. It interposes `malloc`/`calloc`/`realloc` and
aggregates each allocation by call-stack, so memory use is bounded by the number
of distinct allocation stacks rather than the number of allocations -- letting it
profile an allocation-heavy run (a Galacticus model can make billions of
allocations) to completion, where a record-every-event profiler such as heaptrack
exhausts RAM. It counts cumulative allocations including freed temporaries (which
a live-heap profiler cannot see), supports 1-in-N sampling for fast turnaround,
and can report the inclusive share of allocations attributable to a target regex
(e.g. a particular object's construct/destroy lifecycle). See
`allocationProfiler/ReadMe.md` for usage.

```
./allocationProfiler/runAllocProf.sh <program> [args...]
```

### `plotAnalyses.py`

Overlays the on-the-fly `analyses` results stored in Galacticus HDF5 output
files so that a test run can be compared against a reference run. Given a test
path and a reference path -- each either a single HDF5 file or a directory of
them -- it matches files by name, and for every file present in both locations
plots each `function1D` analysis under `/analyses` (the test curve, the
reference curve, and any target/observational overlay) into a PDF. The PDFs are
written into a per-model subdirectory `analyses_<model>/` under the output
directory (the current directory by default). Files present in only one of the
two paths are reported and skipped.

```
./plotAnalyses.py <testPath> <referencePath> [-o <outputDir>] [-g <glob>]
```

Requires the `dendros` package.

### `runBenchmarks.sh`

Runs a set of executables one after the other, repeating the whole set a given number of
times, for micro-benchmarking. Each run is pinned to a single CPU to avoid CPU-to-CPU variation.
If the user has sudo access, the CPU governor is set to `performance` with turbo disabled for the
duration, and restored afterwards.

```
./runBenchmarks.sh [-r <repeats>] -e <executable> [-e <executable> ...]
```

`--repeats` defaults to 3.
