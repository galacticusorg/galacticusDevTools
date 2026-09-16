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

### `classContractSweep.py`

Sweeps a Galacticus checkout for ways in which implementations of one
`functionClass` can disagree with each other or with their consumers, and writes
the full findings to `classContractSweep.json` in the working directory. It
reports five kinds of finding:

* **C1 — optional-argument contracts.** The constraints a method's base `<code>`
  imposes, the arguments individual implementations require (either by an
  explicit `Error_Report` or, marked `*`, inferred from an unguarded use), and
  the consumer call sites which violate the base contract or omit an argument
  some implementation needs.
* **C2 — capability stubs.** Methods whose override in some implementation only
  raises a "not supported" error, together with the consumers which call that
  method on the generic class.
* **C3 — null-default hazards.** Classes whose default implementation is `null`,
  where a consumer calls a method the null implementation answers with an error
  or a `huge()` sentinel.
* **C4 — inherited base defaults.** Methods with base-class default code, and
  which implementations inherit it rather than overriding.
* **C5 — parameter-convention drift.** Within one class: same-named parameters
  differing in type or in the units their descriptions give, and near-duplicate
  parameter names.

```
export GALACTICUS_EXEC_PATH=<dir>
./classContractSweep.py [<parameter-catalog>]
```

The catalog argument enables the C5 checks; build it with
`scripts/build/parameterCatalog.py`. Note that a catalog left in a checkout is
not tracked by git and so may predate the working tree, in which case C5 reports
a state that no longer exists — regenerate it before trusting those findings.

The analysis is regex-based rather than a full parse, so findings are heuristic
and meant to be reviewed rather than acted on blindly. Two specific classes of
false positive are known and worth recognising:

* A near-duplicate parameter pair whose names differ only by a trailing capital
  or acronym — `A`/`B`, `haloMassFunctionA`/`haloMassFunctionP`,
  `coefficient`/`coefficientISM` — is an artifact of how names are split into
  words, and is usually a set of distinct fitting coefficients rather than a
  duplicate.
* A C1 "omits argument" finding against a call site may instead be a capability
  mismatch with no call-site fix: the argument may not exist in that context at
  all, as for an analysis un-operator applied to bin centers after a run, or a
  halo mass function evaluated on a mass grid with no node.

Generic interfaces and calls through `associate` aliases are not resolved, so
consumer counts are lower bounds.

### `namingAudit.py`

Audits API naming consistency across a Galacticus checkout and writes the full
findings to `namingAudit.json`. It reports two kinds of finding:

* **Spelling** — US-spelling violations in Fortran identifiers, in documentation
  prose (`<description>` directive elements and `!!{RST ... !!}` blocks), in
  Python, and in parameter files. This complements the `Spell-Check-RST` CI job,
  which covers only the generated documentation and cannot see identifiers,
  Python, or parameter files.
* **Structural** — class and implementation name styles, vowel-stripped
  implementation-name abbreviations, parameter name style and word order,
  boolean parameters that do not read as predicates, methods that express one
  concept under two word orders, module and procedure name styles, hyphenated
  file names, and property-extractor output names.

```
./namingAudit.py [--repo <dir>] [--catalog <file>] [--spelling] [--structural]
```

`--repo` defaults to `$GALACTICUS_EXEC_PATH`. The structural scan needs the
parameter catalog; if it is not found, the script prints the
`scripts/build/parameterCatalog.py` command that builds it. `--spelling` runs
only the spelling scan, which needs no catalog and no build, and is the mode
intended for a lint job.

The conventions checked, and their deliberate exceptions (cosmological
parameters written as symbols, fitting-formula coefficients written as paper
symbols, `*IsFatal`/`*Only` booleans, legacy `Upper_Snake_Case` procedures), are
documented in the *Naming conventions* section of the Galacticus developer
guide. To keep the two consistent, the script honours `aux/words.dict` — the
dictionary the documentation spelling builder uses — so proper names recorded
there (people, codes, simulations) are not flagged.

Findings are heuristic and meant to be reviewed rather than applied blindly. In
particular, an adjective-first parameter name may be an established physics
term, and an extractor which composes its dataset name from a prefix (for
example `'darkMatterProfileDMO'//propertyName`) correctly has a capitalized name
literal; those are reported separately rather than as defects.

### `promptCusps.py`

Reference implementation used to validate Galacticus' built-in prompt-cusp
model. Uses Sten Delos' [`cusp_halo_relation`](https://github.com/delos/cusp-halo-relation)
Python module to compute power-spectrum integrals σ₀ and σ₂ and the cusp
properties (amplitude, mass, scale radius, scale density, virial radius,
concentration, etc.) of a reference halo, and prints them so that they can be
compared against the values produced by Galacticus' Fortran test
[`tests.prompt_cusps.F90`](https://github.com/galacticusorg/galacticus/blob/master/source/tests.prompt_cusps.F90).

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

### `stellarYields/`

Converters that turn published stellar nucleosynthesis yield tables into the XML
formats Galacticus reads, writing them into the datasets repository. These let
alternative yield sets be added -- and regenerated -- reproducibly: every file
written records its science source, the transcription source where the numbers
came from a redistribution rather than the paper, the retrieval date, the exact
input files, and the script that produced it. The yield files previously shipped
in the datasets repository were built by hand with no such record.

A shared module, `stellarYields/galacticusYieldTables.py`, supplies the writers
for both formats (per-star stellar properties, and Type Ia supernova yields), the
element/atomic-number lookup taken from Galacticus' own atomic data file, and the
provenance record. See `stellarYields/ReadMe.md` for the format conventions --
notably that stellar-properties yields are *net* (and may be negative) while the
Type Ia reader sums every isotope present, so those files must contain metals
only.

```
./stellarYields/convertIwamoto1999.py [--models W7 WDD2 ...]
```

### `blackHolePhysics.py`

Independent reference values for Galacticus' black hole physics, used by
`tests.black_hole_physics.exe`. Computes Kerr metric innermost stable circular orbit
quantities from Bardeen, Press & Teukolsky (1972), the frame-dragging frequency,
Shakura-Sunyaev radiative efficiencies and spin-up rates, Meier (2001) jet powers,
Bondi-Hoyle-Lyttleton accretion, and Rezzolla et al. (2008) binary merger remnant spins
and masses. Written from the published expressions rather than from the Galacticus
implementation.

```
./blackHolePhysics.py
```

Requires `numpy` and `scipy`.

### `starFormationFeedbackPhysics.py`

Independent reference values for star formation rate surface densities and stellar
feedback outflow rates, used by `tests.star_formation_feedback_physics.exe`. Covers the
Kennicutt-Schmidt law with and without a critical surface density, the disk-integrated
star formation rate for an exponential disk in closed form, dynamical-time star formation
timescales, and the power-law and rate-limited outflow classes.

```
./starFormationFeedbackPhysics.py
```

Requires `numpy` and `scipy`.

### `mergersInstabilitiesPhysics.py`

Independent reference values for merger and instability physics, used by
`tests.mergers_instabilities_physics.exe`. Covers the Efstathiou, Lake & Negroponte (1982)
bar instability criterion and timescale, and the Cole et al. (2000) merger remnant size
algorithm including its dark matter term.

```
./mergersInstabilitiesPhysics.py
```

Requires `numpy` and `scipy`.

### `massDefinitionsOutputTimes.py`

Independent reference values for halo mass definitions and output time conversions, used
by `tests.mass_definitions_output_times.exe`. Uses `colossus` and `astropy` for virial
density contrasts, conversions of halo masses between contrast definitions, and
conversions between redshift and cosmic time. Note that Galacticus' density contrasts are
relative to the *mean* matter density while colossus' are relative to the *critical*
density, and that `cosmologyFunctionsMatterLambda` contains no radiation term, so both
reference codes are given `Tcmb0=0`.

```
./massDefinitionsOutputTimes.py
```

Requires `numpy`, `scipy`, `astropy` and `colossus`.

### `coolingChain.py`

Independent reference values for the Galacticus cooling chain, used by
`tests.cooling_chain.exe`: mean density, virial radius, velocity, temperature and
dynamical time, the beta-profile density normalization, the Cloudy cooling function and
electron density tables, the cooling time, the cooling radius, its growth rate, and the
mass cooling rate. The two Cloudy HDF5 files are read directly, being data rather than
code, but the interpolation scheme applied to them is reimplemented from the documented
conventions, since that scheme is itself part of what is checked.

```
./coolingChain.py
```

Requires `numpy`, `scipy` and `h5py`.

### `bett2007SpinDistribution.py`

Independent reference values for the halo spin distribution of Bett et al. (2007), used by
`tests.bett2007_spin_distribution.exe`. Substituting `x = alpha (lambda/lambda_0)^(3/alpha)`
turns the fitting function into a gamma distribution of shape `alpha`, giving the
normalization `3 alpha^(alpha-1)/Gamma(alpha)` and the moments in closed form; the script
checks these against direct quadrature and confirms that the distribution integrates to
unity.

```
./bett2007SpinDistribution.py
```

Requires `numpy` and `scipy`.

### `chabrier2001IMF.py`

Independent reference values for the Chabrier (2001) stellar initial mass function, used by
`tests.initial_mass_functions.exe`. Derives the normalization of each branch in closed form
rather than transcribing the expressions used by Galacticus - the log-normal branch's mass
integral reduces, on completing the square, to an expression in error functions - and
measures the continuity of the two branches as a function of the transition mass. That last
check found a defect in the Galacticus implementation, since fixed.

```
./chabrier2001IMF.py
```

Requires `numpy` and `scipy`.

### `galacticStructureEquilibrium.py`

Independent reference values for the equilibrium galactic structure solver, used by
`tests.galactic_structure_equilibrium.exe`. Solves for the equilibrium radii of an exponential
disk and a Hernquist spheroid in an NFW halo which contracts adiabatically in response to them
(Gnedin et al. 2004), by a plain two-level root find - outer for the coupled radii, inner for
the initial radius at each final radius - where Galacticus reaches the same fixed point by
iteration with oscillation-breaking heuristics. Agreement is therefore a statement about the
solution rather than the algorithm. The module header lists the conventions deliberately taken
from Galacticus, chiefly that the specific angular momentum handed to the solver is half of
J/M, not J/M.

`--tolerance` re-solves every model with the Bessel factor of the disk rotation curve replaced
by the tabulated-and-interpolated form Galacticus uses, and reports how far the radii move;
that measurement, 1.7e-5, is what justifies the companion test's tolerance. `--fortran` emits
the reference values as Fortran array initializers.

```
./galacticStructureEquilibrium.py
./galacticStructureEquilibrium.py --tolerance
./galacticStructureEquilibrium.py --fortran
```

Requires `numpy` and `scipy`.

## License

The tools in this repository are released under the MIT License -- see
[`License.txt`](License.txt). The bundled `delta` source under
`deltaTestCaseReducer/` retains its own BSD license, which is included
alongside it.

### `referenceKing1962.py`

Computes reference values for the King (1962) satellite tidal radius, for use by the
`tests.satellites.tidal_stripping.radius.King1962` unit test in Galacticus. Nothing is
taken from the Galacticus implementation: the script builds NFW host and satellite
profiles with Bryan & Norman (1998) virial radii, forms the tidal pull
`gamma omega^2 - d^2Phi/dR^2`, and solves `G M_sat(<r_t)/r_t^3 = pull` for a set of
orbits. It also computes the radii returned where no tidal radius exists, and checks
itself against the Jacobi radius for point masses. Physical constants are the GSL values
from which Galacticus builds its own, so that no difference in constants enters the
comparison. Values are printed both in full and as Fortran-ready arrays.

```
./referenceKing1962.py
```

Requires `scipy`.

### `benson2005Check.py`

Checks the constants hard-coded in Galacticus' `virialOrbitBenson2005` class against the
fitting function of Benson (2005) as it is coded there: the peak of the distribution
used as the rejection-sampling envelope (`pMax`), the mean magnitude of the tangential
velocity, and the root mean squared total velocity. The latter two are obtained by
direct 2D integration over the fitting function.

```
./benson2005Check.py
```

Requires `numpy` and `scipy`.

### `ccm89Check.py`

Compares Galacticus' transcription of the Cardelli, Clayton & Mathis (1989) extinction
curve (the `dustExtinctionCurveCardelli1989` class) against the independent
implementation in the `dust_extinction` package, over the full range of validity
(0.3 <= x < 8 inverse microns) and for several values of R_V.

```
./ccm89Check.py
```

Requires `numpy`, `astropy`, and `dust_extinction`.

### `sfImpact.py`

Quantifies the effect of two choices in the star formation rate surface density classes:
the characteristic pressure in the Blitz & Rosolowsky (2006) molecular fraction (and the
`min(R,1)` versus `R/(1+R)` forms of that fraction), and the application of the hydrogen
mass fraction to the gas surface density in the Krumholz, McKee & Tumlinson (2009) model.
It reports molecular fractions across a Milky Way-like exponential disk, and across a
range of gas surface densities, for each choice.

```
./sfImpact.py
```

Requires `numpy`.

### `referenceMolecularFractions.py`

Independent reference values for the molecular fraction and star formation rate surface
density laws of Blitz & Rosolowsky (2006) and Krumholz, McKee & Tumlinson (2009), used by
`tests.star_formation.molecular_fractions.exe`: the midplane pressure of a disk of locally
isothermal gas and stars, the molecular-to-atomic ratio and molecular fraction of eqns.
(11) and (21) of the former, the molecular fraction of eqn. (2) of the latter together
with the McKee & Krumholz (2010) fast approximation, and the rate surface density of each.
Every expression is written from the papers; only the hydrogen mass fraction and the Solar
metallicity, which are conventions of the code rather than of either paper, are taken from
Galacticus.

```
./referenceMolecularFractions.py
```

Requires nothing beyond the standard library.

### `referenceVirialOrbits.py`

Independent reference values for the virial orbit distributions of Benson (2005) and Jiang
et al. (2015), used by `tests.satellites.virial_orbits.exe`: the mean tangential velocity
and root mean squared total velocity of the Benson (2005) joint velocity distribution, and
the same two moments of the Jiang et al. (2015) Voigt profile combined with the closed-form
mean tangential velocity implied by their radial velocity distribution, in each of the nine
host mass by mass ratio bins of their Table 2. Both distributions are written from their
papers, including Galacticus' truncation of the Voigt profile, which is part of what is
checked. All velocities are in units of the host virial velocity, so no cosmology enters and
the values are exact.

```
./referenceVirialOrbits.py
```

Requires `numpy` and `scipy`.
