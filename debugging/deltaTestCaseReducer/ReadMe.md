# Delta Debugging script

The `delta.sh` script can reduce a code file to a minimal example that causes a specific error condition to occur by successively removing lines of code. See [here](https://github.com/dsw/delta) for details.

Typically you would use this script by running:
```
./delta.sh -test=testScript.sh -suffix=.F90 file.F90
```
where `file.F90` is the file that you want to reduce, and `testScript.sh` is a script that tests the file (e.g. tries compiling or running it) and returns a zero exit status if the desired error condition occurs, non-zero otherwise.

The file `testScriptExample.sh` in this folder provides an example of a test script.
