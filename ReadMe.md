# Galacticus Dev Tools

A collection of scripts and tools that are helpful in maintaining and developing
[Galacticus](https://github.com/galacticusorg/galacticus). They are not part of
the Galacticus model itself; they are utilities used by developers and
maintainers for housekeeping, data preparation, validation, and CI/CD support
tasks around the main repository.

## Tools

The tools are grouped by purpose into the directories below. Each directory's
`ReadMe.md` describes its tools in full, including usage and requirements.

### [`physicsReferences/`](physicsReferences/ReadMe.md) — physics references

*Black holes and accretion*

* `blackHolePhysics.py` — Kerr ISCO quantities, radiative efficiencies, spin-up, jet powers, Bondi accretion and merger remnants.
* `bensonBabul2009.py` — Benson & Babul (2009) ADAF + jet model, for testing the published results and their variants.
* `bensonBabul2009_galacticusAlpha.py` — The same model with Galacticus' alpha(j) fits, compared against `tests.accretion_disks`.

*Star formation, feedback and the IMF*

* `starFormationFeedbackPhysics.py` — Kennicutt-Schmidt star formation, dynamical-time timescales, and stellar feedback outflow rates.
* `referenceMolecularFractions.py` — Blitz & Rosolowsky (2006) and Krumholz, McKee & Tumlinson (2009) molecular fractions.
* `sfImpact.py` — The effect of two modelling choices on molecular fractions in the star formation rate classes.
* `chabrier2001IMF.py` — Chabrier (2001) IMF normalizations in closed form, and continuity of its two branches.

*Halos and cosmology*

* `massDefinitionsOutputTimes.py` — Halo mass definition conversions and redshift/time conversions, via colossus and astropy.
* `bett2007SpinDistribution.py` — Bett et al. (2007) halo spin distribution normalization and moments.
* `halofitDecompose.py` — Smith et al. (2003) halofit, separating the quasi-linear and halo terms.
* `promptCusps.py` — Prompt-cusp properties from Delos' `cusp_halo_relation` module.

*Mass distributions and galactic structure*

* `massDistributionProfilesCheck.py` — Einasto and Burkert profiles, by numerical integration of the density.
* `exponentialDiskAccelerations.py` — Accelerations, potential and mid-plane rotation curve of a thick (sech²) exponential disk, by direct convolution of the vertical profile.
* `zhao1996DispersionCheck.py` — Zhao (1996) velocity dispersions, by numerical solution of the Jeans equation.
* `galacticStructureEquilibrium.py` — Equilibrium radii of a disk and spheroid in an adiabatically contracting NFW halo.
* `mergersInstabilitiesPhysics.py` — Bar instability criterion and timescale, and the Cole et al. (2000) merger remnant size.

*Gas cooling and chemistry*

* `coolingChain.py` — The hot halo cooling chain, from virial quantities through to the mass cooling rate.
* `hydrogenNetworkCheck.py` — Abel et al. (1997) primordial hydrogen network rate coefficients and cross-sections.

*Satellites*

* `referenceKing1962.py` — King (1962) satellite tidal radius.
* `referenceVirialOrbits.py` — Benson (2005) and Jiang et al. (2015) virial orbit distribution moments.
* `benson2005Check.py` — Checks the constants hard-coded in Galacticus' Benson (2005) virial orbit class.
* `satelliteOrbitRates.py` — Dynamical friction and tidal mass loss rates, pointwise.
* `satelliteOrbitEvolution.py` — A satellite orbit integrated in a static host, checking the assembly of those rates.
* `satelliteTidalHeatingRate.py` — Gnedin, Hernquist & Ostriker (1999) tidal heating rate, pointwise.
* `satelliteTidalHeatingEvolution.py` — Tidal heating accumulated along a satellite orbit.
* `satelliteHeatedProfile.py` — The response of a dark matter profile to tidal heating.

*Spectra and dust*

* `ccm89Check.py` — Cardelli, Clayton & Mathis (1989) extinction curve against `dust_extinction`.
* `meiksin2006Check.py` — Meiksin (2006) intergalactic attenuation.

### [`codeAudits/`](codeAudits/ReadMe.md) — code audits

* `classContractSweep.py` — Finds ways implementations of a `functionClass` disagree with each other or with their consumers.
* `namingAudit.py` — Audits spelling and naming-convention consistency across the code base.

### [`maintenance/`](maintenance/ReadMe.md) — maintenance

* `GPLerize.py` — Adds or refreshes the GPL header on Fortran and C/C++ source files.
* `migrateAllParameterFiles.py` — Migrates every bundled parameter file to the current schema.
* `retrieveGHPagesArtifacts.sh` — Merges a CI run's metric artifacts into a local `gh-pages` checkout for preview.

### [`debugging/`](debugging/ReadMe.md) — debugging, testing and profiling

* `parameterFuzzer/` — Fuzzes the parameter space, clusters failures, and reduces each to a minimal reproducer.
* `deltaTestCaseReducer/` — Reduces a source file to a minimal case that still triggers an error, using Delta.
* `allocationProfiler/` — `LD_PRELOAD` profiler attributing heap-allocation churn to call stacks.
* `plotAnalyses.py` — Overlays on-the-fly analysis results from a test run and a reference run.
* `runBenchmarks.sh` — Runs executables repeatedly, pinned to one CPU, for micro-benchmarking.

### [`dataPreparation/`](dataPreparation/ReadMe.md) — data preparation

* `extractSDSSBPTData.py` — Builds SDSS DR8 emission-line flux datasets for star-forming galaxies and AGN.
* `stellarYields/` — Converts published stellar yield tables into the XML formats Galacticus reads.

## License

The tools in this repository are released under the MIT License -- see
[`License.txt`](License.txt). The bundled `delta` source under
`debugging/deltaTestCaseReducer/` retains its own BSD license, which is included
alongside it.
