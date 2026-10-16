# Data preparation

Scripts which build the datasets Galacticus reads from published catalogs and tables, recording
the provenance of every file they write.

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

### `convertSKIRTOR.py`

Converts the SKIRTOR library of AGN dusty torus SEDs (Stalevski et al. 2012,
2016) into the HDF5 tabulation read by Galacticus' `dustAttenuationAGNTorusSKIRTOR`
and `dustEmissionSpectrumAGNTorusSKIRTOR` classes:

```
convertSKIRTOR.py skirtor_2016-7-18.zip SKIRTOR_2016-7-18.hdf5
```

The zip archive, and the `total_dust_mass_2016-7-18.txt` file to be placed alongside
it, are from the [SKIRTOR site](https://sites.google.com/site/skirtorus/sed-library).
For each of the 1920 models and 10 inclinations it writes the line-of-sight
transmission (direct/transparent), the scattered flux relative to the transparent
flux averaged over directions, and the dust emission per unit accretion-disk
luminosity, plus the dust emission averaged over directions. It checks that every
model shares one wavelength grid and that the transparent flux follows the
Netzer (1987) angular distribution SKIRTOR assumes. The output records its
provenance (source URL, MD5 checksum of the zip, git revision of this script,
and a timestamp) as HDF5 attributes. Galacticus looks for the result in
`dust/agnTorus/` under the dynamic datasets path.

Requires `numpy`, `h5py`, and `gitpython`.

### `convertCLUMPY.py`

Converts the CLUMPY library of AGN clumpy dusty torus SEDs (Nenkova et al. 2008a,b)
into the HDF5 tabulation read by Galacticus' `dustEmissionSpectrumAGNTorusCLUMPY`
class:

```
convertCLUMPY.py clumpy_models_201410_tvavg.hdf5 CLUMPY_201410_tvavg.hdf5
```

The input is the 1.2 GB file from the [CLUMPY site](https://www.clumpy.org/seds/).
For each of its 124,740 models (N0, Y, q, sigma, tauV) it averages the torus
spectrum (thermal emission plus scattered light, per unit AGN luminosity) over all
directions, integrating over the cosine of inclination with the spectrum
interpolated linearly in inclination, and writes it as one array indexed by the five
parameters and wavelength, together with each model's covering fraction and its
direction-averaged probability for the AGN to be seen unobscured. It checks that the
library is a complete grid. The output records its provenance (source URL, MD5
checksum of the input, git revision of this script, and a timestamp) as HDF5
attributes. Galacticus looks for the result in `dust/agnTorus/` under the dynamic
datasets path.

Requires `numpy`, `h5py`, and `gitpython`.

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
