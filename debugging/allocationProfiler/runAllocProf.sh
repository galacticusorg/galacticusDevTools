#!/usr/bin/env bash

# Convenience wrapper to profile a program's allocations with `liballocProf.so` and summarise the result.
# Andrew Benson (03-June-2026).

# Builds liballocProf.so (from allocProf.c) if needed, runs the given command under LD_PRELOAD so that
# every allocation is aggregated by call-stack into a bounded-memory profile, then symbolises and
# summarises it with analyzeAllocProf.py. The first token of the command is used as the executable for
# symbolisation, so it must be the program that does the allocating (e.g. Galacticus.exe).
#
# Usage:
#   ./runAllocProf.sh <program> [args...]
#
# Environment:
#   ALLOCPROF_SAMPLE  record 1-in-N allocations (default 1 = all; >1 is much faster, ratios stay unbiased).
#   ALLOCPROF_DEPTH   backtrace frames captured per allocation (default 32).
#   ALLOCPROF_OUT     profile output file (default "allocProf.out" in the current directory).
#   ALLOCPROF_REGEX   optional target regex passed to the analyser for inclusive attribution.
#
# Note: the program is run unchanged, so set any environment it needs (for Galacticus, e.g.
# GALACTICUS_DATA_PATH and LD_LIBRARY_PATH) before invoking this script. Profiling adds a stack unwind
# per recorded allocation, so for very allocation-heavy runs use ALLOCPROF_SAMPLE and a single thread.

set -euo pipefail

if [[ $# -lt 1 ]]; then
    echo "usage: runAllocProf.sh <program> [args...]" >&2
    exit 2
fi

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
lib="${here}/liballocProf.so"
prog="$1"

export ALLOCPROF_OUT="${ALLOCPROF_OUT:-allocProf.out}"
export ALLOCPROF_DEPTH="${ALLOCPROF_DEPTH:-32}"
export ALLOCPROF_SAMPLE="${ALLOCPROF_SAMPLE:-1}"

# Build / refresh the preload library if needed.
if [[ ! -f "${lib}" || "${here}/allocProf.c" -nt "${lib}" ]]; then
    echo ">> building $(basename "${lib}")"
    gcc -O2 -fPIC -shared -o "${lib}" "${here}/allocProf.c" -ldl -lpthread
fi

echo ">> profiling: $*"
[[ "${ALLOCPROF_SAMPLE}" -gt 1 ]] && echo "   (sampling 1-in-${ALLOCPROF_SAMPLE})"
LD_PRELOAD="${lib}${LD_PRELOAD:+:${LD_PRELOAD}}" "$@"

[[ -s "${ALLOCPROF_OUT}" ]] || { echo "error: no profile written to ${ALLOCPROF_OUT}" >&2; exit 1; }

echo
"${here}/analyzeAllocProf.py" "${prog}" "${ALLOCPROF_OUT}" ${ALLOCPROF_REGEX:+"${ALLOCPROF_REGEX}"}
