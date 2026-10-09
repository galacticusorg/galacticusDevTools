# allocationProfiler

A lightweight `LD_PRELOAD` allocation profiler for finding which call sites are
responsible for a program's heap-allocation churn — built to answer questions
like "how much of this model's allocation activity comes from constructing and
destroying a particular object?".

It interposes `malloc`/`calloc`/`realloc` and, for each allocation, captures a
backtrace and aggregates it into a hash table keyed by call-stack. Because only
the *aggregated* per-stack counts are kept, memory use is bounded by the number
of distinct allocation stacks — **not** by the number of allocations. This is
what lets it profile an allocation-heavy run (a Galacticus model can make
billions of allocations) all the way to completion, where a record-every-event
profiler such as [heaptrack](https://github.com/KDE/heaptrack) runs out of RAM.
It counts *cumulative* allocations, including short-lived temporaries that are
quickly freed, which a live-heap profiler (e.g. jemalloc's) cannot see.

## Components

- `allocProf.c` — the preload library. Build:
  ```
  gcc -O2 -fPIC -shared -o liballocProf.so allocProf.c -ldl -lpthread
  ```
- `analyzeAllocProf.py` — symbolises a profile (inlining-aware `addr2line`) and
  reports the total allocations/bytes, the busiest allocation call sites, and —
  given a target regex — the inclusive share of allocations whose stack passes
  through any matching frame.
- `runAllocProf.sh` — convenience wrapper that builds the library if needed,
  runs a command under `LD_PRELOAD`, and summarises the result.

## Usage

The simplest path is the wrapper, which profiles any command:

```
./runAllocProf.sh ./yourProgram args...
```

For an allocation-heavy run, sample (much faster; attribution ratios remain
statistically unbiased), and optionally attribute to a target subsystem:

```
ALLOCPROF_SAMPLE=50 ALLOCPROF_REGEX='nfwget|massdistributionnfw' \
  ./runAllocProf.sh ./Galacticus.exe myModel.xml
```

Or drive the pieces directly:

```
gcc -O2 -fPIC -shared -o liballocProf.so allocProf.c -ldl -lpthread
ALLOCPROF_OUT=alloc.out ALLOCPROF_SAMPLE=50 LD_PRELOAD=./liballocProf.so ./Galacticus.exe myModel.xml
./analyzeAllocProf.py ./Galacticus.exe alloc.out 'nfwget|massdistributionnfw'
```

The program is run unchanged, so set whatever environment it needs (for
Galacticus, e.g. `GALACTICUS_DATA_PATH` and `LD_LIBRARY_PATH`) beforehand.

## Environment variables

| variable           | default          | meaning                                                            |
|--------------------|------------------|--------------------------------------------------------------------|
| `ALLOCPROF_SAMPLE` | `1` (all)        | record 1-in-N allocations; N>1 unwinds ~1/N as often, scaling counts so totals stay estimates of the true totals while ratios remain unbiased |
| `ALLOCPROF_DEPTH`  | `32`             | backtrace frames captured per allocation                           |
| `ALLOCPROF_OUT`    | `allocProf.out`  | profile output file                                                |
| `ALLOCPROF_REGEX`  | _(unset)_        | target regex for inclusive attribution (wrapper only)              |

## Notes and caveats

- The backtrace uses the libgcc `.eh_frame` unwinder, so it works on optimised
  (`-O3`, no frame pointer) builds. The executable should be built with debug
  information (`-g`) for `addr2line` to resolve names. The overhead is CPU (a
  stack unwind per recorded allocation), not memory — so prefer
  `ALLOCPROF_SAMPLE` and a single thread for the fastest turnaround.
- Profiles are per-process and written at exit; the program must exit (or be
  terminated by a catchable signal it flushes on) for the profile to be written.
- For multi-threaded runs the aggregation is serialised by a mutex (taken only
  when a sample is recorded); a single thread gives the cleanest, fastest
  attribution.
- Linux/glibc only.
