# Maintenance

Housekeeping tools for a Galacticus checkout and its CI/CD outputs.

### `GPLerize.py`

Adds (or refreshes) the standard Galacticus GPL header on every Fortran
(`.f`, `.f90`, `.inc`) and C/C++ (`.c`, `.cpp`, `.h`) source file in a given
directory. The copyright year range is generated dynamically from 2009 to the
current year, and any pre-existing comment header at the top of the file is
stripped before the new one is written. The original file is preserved as a
`~`-suffixed backup.

```
./GPLerize.py <sourceDir>
```

### `migrateAllParameterFiles.py`

Runs `scripts/aux/parametersMigrate.py` in-place on the default parameter file
(`parameters.xml`, at the root of a Galacticus checkout) and on every XML
parameter file found by walking the `parameters`, `constraints`, and
`testSuite` directories, so that all bundled parameter files are migrated to
the current schema in a single pass. Files that are not Galacticus parameter
files (no top-level `<parameters>` element) and a fixed set of excluded
sub-directories (e.g. `testSuite/outputs`) are skipped. The test suite's
`strictOutdated.xml`, `unstrictOutdated.xml`, and `parameterMigration.xml` are
also skipped: they are deliberately outdated, to exercise the "outdated
parameter file" and migration code paths.

Run from the root of a Galacticus checkout with `GALACTICUS_EXEC_PATH` set to
the Galacticus executable directory.

### `retrieveGHPagesArtifacts.sh`

Pulls validation, benchmark, and build-profile artifacts from a Galacticus
CI/CD run and merges them into a local `gh-pages` checkout, so that a PR's
metric pages can be inspected before the PR is merged and its results are
deployed for real. The set of metrics to update is read from
`scripts/build/ghPagesMetricsManifest.yml` (the same manifest the CI
regenerator uses), so adding a new metric requires no change to this script.
If `GALACTICUS_EXEC_PATH` points at a checkout of Galacticus master, the
manifest, threshold sidecar, and `buildGhPagesIndex.py` indexer are taken from
there and the indexer is run automatically; otherwise the manifest is fetched
from upstream master, the indexer step is skipped, and the script prints the
command needed to regenerate the index manually. Each touched per-metric page
is opened in the default browser at the end of the run.

```
./retrieveGHPagesArtifacts.sh <runID>
```

Run from a directory with the `gh-pages` branch of Galacticus checked out.
Requires the GitHub CLI (`gh`).
