#!/bin/sh

# Example test script for the delta debugging script.

# Get the file to be tested.
FILE=$1

# Compile the file, sending output to a log file.
gfortran -c $FILE -o tmp.o &> test.out

# Check for the existance of phrase indicating error condition is present in the log file.
grep -q "gcc-trunk-upstream/gcc/toplev.c:352" test.out

exit
