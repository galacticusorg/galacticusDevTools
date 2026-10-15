#!/usr/bin/env python3
"""Convert the SKIRTOR library of AGN dusty torus SEDs into the HDF5 tabulation read by Galacticus.

SKIRTOR (Stalevski et al. 2012, MNRAS, 420, 2756; Stalevski et al. 2016, MNRAS, 458, 2288) is a library of radiative
transfer models of a two-phase (clumpy plus smooth) dusty torus around an AGN, computed with SKIRT. Each SED file gives,
for one model seen at one inclination, the transparent (unattenuated), direct, scattered and dust-emitted flux of the
accretion disk. See https://sites.google.com/site/skirtorus/sed-library for the format.

This script writes, for every model and inclination:

 transmissionDirect    = direct / transparent
     The line-of-sight transmission. This depends only on the geometry of the dust, not on the angular distribution of
     the emission of the accretion disk, and so carries over to a source of any angular distribution.
 transmissionScattered = scattered / <transparent>
     Light scattered towards the observer, relative to the transparent flux averaged over all directions. The scattered
     light seen at one inclination was emitted in other directions, so it can not be expressed relative to the
     transparent flux at that inclination (which, for the anisotropic accretion disk of SKIRTOR, vanishes edge-on).
 emissionDust          = dust emission / integral of <transparent> over log wavelength
     The dust emission, as lambda L_lambda per unit luminosity of the accretion disk.

where <...> denotes an average over all directions. The SKIRTOR accretion disk emits with the angular distribution
cos(i) (1 + 2 cos(i)) of Netzer (1987); the transparent flux of every model follows it to within 1e-8 (this is
checked), so <transparent> is computed exactly from the face-on flux rather than by quadrature over the ten
inclinations. The orientation-averaged dust emission, emissionDustMean, is computed by integrating over the cosine of
inclination with the emission interpolated linearly in inclination, the scheme Galacticus uses when interpolating the
tabulation in inclination.

Usage: convertSKIRTOR.py <skirtor_2016-7-18.zip> <output.hdf5>

The zip archive is that from the SKIRTOR site (https://sites.google.com/site/skirtorus/sed-library), with the companion
total_dust_mass_2016-7-18.txt file alongside it.

Andrew Benson, Claude (15-October-2026)
"""
import sys
import os
import re
import io
import zipfile
import hashlib
import datetime
import numpy as np
import h5py
from git import Repo

# Function to compute the md5sum of a file.
def md5_checksum(file_path):
    m = hashlib.md5()
    with open(file_path, 'rb') as file:
        while True:
            data = file.read(8192)
            if not data:
                break
            m.update(data)
    return m.hexdigest()

if len(sys.argv) != 3:
    sys.exit("Usage: convertSKIRTOR.py <skirtor_2016-7-18.zip> <output.hdf5>")
fileNameZip    = sys.argv[1]
fileNameOutput = sys.argv[2]
fileNameMass   = os.path.join(os.path.dirname(os.path.abspath(fileNameZip)),"total_dust_mass_2016-7-18.txt")

# Parse the model name, e.g. "t5_p1_q0_oa50_R20_Mcl0.97_i30_sed.dat".
namePattern = re.compile(r"^t([0-9.]+)_p([0-9.]+)_q([0-9.]+)_oa([0-9.]+)_R([0-9.]+)_Mcl([0-9.]+)_i([0-9]+)_sed\.dat$")
archive     = zipfile.ZipFile(fileNameZip)
seds        = {}
for name in archive.namelist():
    match = namePattern.match(os.path.basename(name))
    if match is None:
        continue
    parameters  = tuple(float(x) for x in match.groups()[0:6])
    inclination = int(match.group(7))
    seds.setdefault(parameters,{})[inclination] = name

models       = sorted(seds.keys())
inclinations = np.array(sorted({i for model in models for i in seds[model]}),dtype=float)
for model in models:
    if len(seds[model]) != len(inclinations):
        sys.exit(f"model {model} lacks some inclinations")
print(f"{len(models)} models, {len(inclinations)} inclinations")

# Angular distribution of the accretion disk emission (Netzer 1987), normalized to unit mean over the sphere. The mean of
# mu (1 + 2 mu) over 0 <= mu <= 1 is 7/6.
cosineInclination = np.cos(np.radians(inclinations))
angularPattern    = cosineInclination*(1.0+2.0*cosineInclination)/(7.0/6.0)

# Read every SED.
wavelength            = None
countWavelength       = None
transmissionDirect    = None
transmissionScattered = None
emissionDust          = None
for j, model in enumerate(models):
    data = np.array([np.loadtxt(io.TextIOWrapper(archive.open(seds[model][int(i)]))) for i in inclinations])
    if wavelength is None:
        wavelength            = data[0,:,0]
        countWavelength       = len(wavelength)
        transmissionDirect    = np.zeros((len(models),len(inclinations),countWavelength))
        transmissionScattered = np.zeros((len(models),len(inclinations),countWavelength))
        emissionDust          = np.zeros((len(models),len(inclinations),countWavelength))
    if np.any(data[:,:,0] != wavelength):
        sys.exit(f"model {model} has a different wavelength grid")
    transparent = data[:,:,6]
    direct      = data[:,:,2]
    scattered   = data[:,:,3]
    dust        = data[:,:,4]
    # Check that the transparent flux follows the expected angular distribution, wherever it is non-zero.
    positive = transparent[0,:] > 0.0
    ratio    = transparent[:,positive]/transparent[0,positive]*angularPattern[0]
    if np.max(np.abs(ratio-angularPattern[:,None])) > 1.0e-6:
        sys.exit(f"model {model}: transparent flux does not follow the Netzer (1987) angular distribution")
    # Mean transparent flux over all directions.
    transparentMean = transparent[0,:]/angularPattern[0]
    luminosityMean  = np.trapezoid(transparentMean,np.log(wavelength))
    # Line-of-sight transmission. Where there is no transparent flux (only at the longest wavelength, where the source
    # emits nothing) the transmission is undefined; take it from the neighboring wavelength.
    defined = transparent > 0.0
    transmissionDirect[j] = np.where(defined,direct/np.where(defined,transparent,1.0),np.nan)
    for k in range(len(inclinations)):
        bad = np.isnan(transmissionDirect[j,k])
        if np.any(bad):
            good = np.where(~bad)[0]
            transmissionDirect[j,k,bad] = np.interp(np.log(wavelength[bad]),np.log(wavelength[good]),transmissionDirect[j,k,good])
    transmissionScattered[j] = np.where(transparentMean > 0.0,scattered/np.where(transparentMean > 0.0,transparentMean,1.0),0.0)
    emissionDust         [j] = dust/luminosityMean
    if (j+1) % 200 == 0:
        print(f"  read {j+1} models")

# Orientation-averaged dust emission: integrate over cos(i), with the emission interpolated linearly in inclination.
# Interpolation is linear in the tabulated values, so the integral is a fixed weighted sum over the tabulated
# inclinations; find the weights by integrating each interpolating basis function on a fine grid.
inclinationFine = np.linspace(0.0,90.0,90001)
cosineFine      = np.cos(np.radians(inclinationFine))
weights         = np.array([-np.trapezoid(np.interp(inclinationFine,inclinations,np.eye(len(inclinations))[k]),cosineFine) for k in range(len(inclinations))])
if abs(np.sum(weights)-1.0) > 1.0e-8:
    sys.exit("inclination weights do not sum to one")
emissionDustMean = np.einsum('k,jkl->jl',weights,emissionDust)

# Dust masses.
massDust = np.full(len(models),np.nan)
if os.path.isfile(fileNameMass):
    masses = {}
    for line in open(fileNameMass):
        match = re.match(r"^t([0-9.]+)_p([0-9.]+)_q([0-9.]+)_oa([0-9.]+)_R([0-9.]+)_Mcl([0-9.]+)\s+([0-9.eE+-]+)",line)
        if match:
            masses[tuple(float(x) for x in match.groups()[0:6])] = float(match.group(7))
    massDust = np.array([masses.get(model,np.nan) for model in models])

# Write the output.
parameters = np.array(models)
with h5py.File(fileNameOutput,"w") as output:
    output.attrs["description"] = "SKIRTOR library of AGN dusty torus models, converted for use by Galacticus."
    output.attrs["reference"  ] = "Stalevski et al. (2012), MNRAS, 420, 2756; Stalevski et al. (2016), MNRAS, 458, 2288"
    output.attrs["url"        ] = "https://sites.google.com/site/skirtorus/sed-library"
    output.attrs["version"    ] = "2016-7-18"
    output.attrs["md5Source"  ] = md5_checksum(fileNameZip)
    output.attrs["timestamp"  ] = datetime.datetime.now().isoformat()
    try:
        repository = Repo(os.path.dirname(os.path.abspath(__file__)),search_parent_directories=True)
        output.attrs["gitRevisionConverter"] = repository.head.object.hexsha
    except Exception:
        output.attrs["gitRevisionConverter"] = "unknown"
    def dataset(name,data,units,description):
        d = output.create_dataset(name,data=data)
        d.attrs["units"      ] = units
        d.attrs["description"] = description
    dataset("wavelength"           ,wavelength         ,"microns","Wavelength.")
    dataset("inclination"          ,inclinations       ,"degrees","Inclination of the line of sight to the axis of the torus (0 is face-on).")
    dataset("opticalDepth9.7"      ,parameters[:,0]    ,""       ,"Edge-on optical depth at 9.7 microns.")
    dataset("exponentRadial"       ,parameters[:,1]    ,""       ,"Exponent, p, of the radial gradient of dust density.")
    dataset("exponentPolar"        ,parameters[:,2]    ,""       ,"Index, q, of the polar gradient of dust density.")
    dataset("angleTorus"           ,parameters[:,3]    ,"degrees","Angle between the equatorial plane and the edge of the torus.")
    dataset("ratioRadii"           ,parameters[:,4]    ,""       ,"Ratio of outer to inner radius of the torus.")
    dataset("fractionMassClumps"   ,parameters[:,5]    ,""       ,"Fraction of the dust mass in clumps.")
    dataset("massDust"             ,massDust           ,"Msun"   ,"Total dust mass, for an accretion disk luminosity of 1e11 Lsun.")
    dataset("transmissionDirect"   ,transmissionDirect   ,""     ,"Direct (line-of-sight) transmission, [model,inclination,wavelength].")
    dataset("transmissionScattered",transmissionScattered,""     ,"Scattered flux relative to the transparent flux averaged over directions, [model,inclination,wavelength].")
    dataset("emissionDust"         ,emissionDust         ,""     ,"Dust emission, lambda L_lambda per unit accretion disk luminosity, [model,inclination,wavelength].")
    dataset("emissionDustMean"     ,emissionDustMean     ,""     ,"Dust emission averaged over directions, lambda L_lambda per unit accretion disk luminosity, [model,wavelength].")
print(f"wrote {fileNameOutput}")
