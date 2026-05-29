#!/usr/bin/env bash

# Simple script used to run micro-benchmarks.
# Andrew Benson (18-May-2026)

# Runs a given set of executables one after the other, and repeats the specified number of times.
# Each executable run is pinned to a single CPU to avoid CPU-to-CPU variations.
# If sudo access is possible, then CPU is set to performance mode, with no turbo - this avoids CPU rate variations.

# Set defaults.
REPEATS=3
EXES=()

# Get options.
# Loop through all arguments
while [[ "$#" -gt 0 ]]; do
    case $1 in
        -r|--repeats) REPEATS="$2"; shift ;;
        -e|--executable) EXES+=("$2"); shift ;;
        *) echo "Unknown parameter: $1"; exit 1 ;;
    esac
    shift # Move to the next argument
done

# Test if we have sudo access.
groups | grep -q -e sudo -e wheel
if [[ $? -eq 0 ]]; then
    haveSudo=1
else
    haveSudo=0
fi

# One-time setup
if [[ $haveSudo -eq 1 ]]; then
    sudo cpupower frequency-set -g performance
    echo 1 | sudo tee /sys/devices/system/cpu/intel_pstate/no_turbo
fi

# Iterate.
for ((i=1; i<=${REPEATS}; i++)); do
    echo Iteration ${i}
    
    # Run
    for exe in "${EXES[@]}"; do
	echo Running ${exe}
	taskset -c 3 ${exe}
	echo
	echo
    done
    
done

# Restore
if [[ $haveSudo -eq 1 ]]; then
    echo 0 | sudo tee /sys/devices/system/cpu/intel_pstate/no_turbo
    sudo cpupower frequency-set -g schedutil
fi
