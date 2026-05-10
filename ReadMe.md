# Galacticus Dev Tools

A collection of scripts and tools that are helpful in maintaining and developing
[Galacticus](https://github.com/galacticusorg/galacticus). They are not part of
the Galacticus model itself; they are utilities used by developers and
maintainers for housekeeping, data preparation, validation, and CI/CD support
tasks around the main repository.

## Tools

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

### `extractSDSSBPTData.py`

Builds the HDF5 datasets of emission-line fluxes for star-forming galaxies and
AGN that Galacticus uses as observational constraints, drawn from the SDSS DR8
MPA-JHU value-added catalogs. The script downloads `galSpecExtra-dr8.fits` and
`galSpecLine-dr8.fits` if they are not already present, splits the sample by
BPT class, and writes
`emissionLineFluxesStarFormingSDSSDR8.hdf5` and
`emissionLineFluxesAGNSDSSDR8.hdf5` to
`${GALACTICUS_DATA_PATH}/static/observations/emissionLines/`. Each output
records its provenance (source URL, git revision of this script, MD5 checksums
of the input FITS files, and a timestamp) as HDF5 attributes.

Requires `numpy`, `h5py`, `astropy`, and `gitpython`, and the
`GALACTICUS_DATA_PATH` environment variable.

### `migrateAllParameterFiles.py`

Walks the `parameters`, `constraints`, and `testSuite` directories of a
Galacticus checkout and runs `scripts/aux/parametersMigrate.py` on every XML
parameter file in-place, so that all bundled parameter files are migrated to
the current schema in a single pass. Files that are not Galacticus parameter
files (no top-level `<parameters>` element) and a fixed set of excluded
sub-directories (e.g. `testSuite/outputs`) are skipped. After migration the
script also resets the `lastModified revision` recorded in the test suite's
`strictOutdated.xml` and `unstrictOutdated.xml` files, which deliberately
exercise the "outdated parameter file" code paths.

Run from the root of a Galacticus checkout with `GALACTICUS_EXEC_PATH` set to
the Galacticus executable directory.

### `promptCusps.py`

Reference implementation used to validate Galacticus' built-in prompt-cusp
model. Uses Sten Delos' [`cusp_halo_relation`](https://github.com/delos/cusp-halo-relation)
Python module to compute power-spectrum integrals σ₀ and σ₂ and the cusp
properties (amplitude, mass, scale radius, scale density, virial radius,
concentration, etc.) of a reference halo, and prints them so that they can be
compared against the values produced by Galacticus' Fortran test
[`tests.prompt_cusps.F90`](https://github.com/galacticusorg/galacticus/blob/master/source/tests.prompt_cusps.F90).

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

### `deltaTestCaseReducer/`

Wrapper around the [Delta debugging tool](https://github.com/dsw/delta) for
reducing a Galacticus source file to a minimal example that still triggers a
specific error (a compiler bug, a runtime crash, etc.) by successively
removing lines. See `deltaTestCaseReducer/ReadMe.md` for usage and
`testScriptExample.sh` for an example test script. The `delta` source itself
is redistributed under its original BSD license; see
`deltaTestCaseReducer/License.txt`.

## License

The tools in this repository are released under the MIT License -- see
[`License.txt`](License.txt). The bundled `delta` source under
`deltaTestCaseReducer/` retains its own BSD license, which is included
alongside it.
