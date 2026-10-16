#!/usr/bin/env python3
"""Convert the CLUMPY library of AGN clumpy dusty torus SEDs into the HDF5 tabulation read by Galacticus.

CLUMPY (Nenkova et al. 2008a, ApJ, 685, 147; Nenkova et al. 2008b, ApJ, 685, 160) is a library of models of the emission
of a torus of optically thick dusty clouds around an AGN. Clouds are distributed about the equatorial plane such that the
mean number met along a ray at angle beta from that plane is N(beta) = N0 exp(-beta^2/sigma^2), with a radial distribution
of clouds proportional to r^-q extending to Y times the radius at which dust sublimates, and each cloud having an optical
depth tauV in the V band. See https://www.clumpy.org/seds/ for the library.

The library tabulates, for each model (N0, Y, q, sigma, tauV) seen at ten inclinations (i, from face-on to edge-on), the
spectrum lambda F_lambda of the torus alone (flux_tor) - its thermal emission and the light it scatters - in units of
the bolometric flux of the AGN. This script averages that spectrum over all directions, so that it gives lambda L_lambda
per unit luminosity of the AGN, and writes it as emissionDustMean[N0,Y,q,sigma,tauV,wavelength]. The average integrates
over the cosine of inclination with the spectrum interpolated linearly in inclination, the scheme Galacticus uses for
tabulations in inclination. The covering fraction of each model (f2) and its probability for the AGN to be seen
unobscured, averaged over directions in the same way (ptype1), are written too.

Usage: convertCLUMPY.py <clumpy_models_201410_tvavg.hdf5> <output.hdf5>

The input file is that from https://www.clumpy.org/downloads/clumpy_models_201410_tvavg.hdf5.

Andrew Benson, Claude (15-October-2026)
"""
import sys
import os
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
    sys.exit("Usage: convertCLUMPY.py <clumpy_models_201410_tvavg.hdf5> <output.hdf5>")
fileNameInput  = sys.argv[1]
fileNameOutput = sys.argv[2]

# Read the parameters of every model, and find the grid of each.
library    = h5py.File(fileNameInput,"r")
names      = ("N0","Y","q","sig","tv","i")
parameters = {name: library[name][:] for name in names}
grids      = {name: np.unique(parameters[name]) for name in names}
for name in names:
    print(f"{name:>4}: {', '.join(str(x) for x in grids[name])}")
shape = tuple(len(grids[name]) for name in names)
if np.prod(shape) != len(parameters["i"]):
    sys.exit("the library is not a complete grid of models")

# Place each model on the grid, and check that every point of it is filled exactly once.
indices = tuple(np.searchsorted(grids[name],parameters[name]) for name in names)
flat    = np.ravel_multi_index(indices,shape)
if len(np.unique(flat)) != len(flat):
    sys.exit("the library has more than one model at some point of the grid")

# Weights for the average over orientation: integrate over cos(i), with the tabulation interpolated linearly in
# inclination. Interpolation is linear in the tabulated values, so the average is a fixed weighted sum over the tabulated
# inclinations; each weight is the integral of the interpolating basis function of its inclination, found analytically.
inclination = np.radians(grids["i"].astype(float))
weights     = np.zeros(len(inclination))
for k in range(len(inclination)-1):
    lower       = inclination[k  ]
    upper       = inclination[k+1]
    width       = upper-lower
    weights[k  ] += (+width*np.cos(lower)+np.sin(lower)-np.sin(upper))/width
    weights[k+1] += (-width*np.cos(upper)+np.sin(upper)-np.sin(lower))/width
if inclination[0] != 0.0 or abs(inclination[-1]-np.pi/2.0) > 1.0e-12 or abs(np.sum(weights)-1.0) > 1.0e-12:
    sys.exit("the inclinations do not span face-on to edge-on")

# Average over orientation. Read the spectra in blocks to limit the memory used.
wavelength       = library["wave"][:]
order            = np.argsort(flat)
emissionDustMean = np.zeros(shape[0:5]+(len(wavelength),))
countModel       = int(np.prod(shape[0:5]))
countInclination = shape[5]
countBlock       = 20000
for start in range(0,countModel,countBlock):
    stop  = min(start+countBlock,countModel)
    rows  = order[start*countInclination:stop*countInclination]
    # h5py requires increasing indices for a selection, and reads a contiguous block (as the library is ordered) far faster.
    rowsSorted = np.sort(rows)
    if rowsSorted[-1]-rowsSorted[0]+1 == len(rowsSorted):
        spectra = library["flux_tor"][rowsSorted[0]:rowsSorted[-1]+1,:].astype(float)
    else:
        spectra = library["flux_tor"][rowsSorted,:].astype(float)
    spectra    = spectra[np.argsort(np.argsort(rows))]
    spectra    = spectra.reshape(stop-start,countInclination,len(wavelength))
    emissionDustMean.reshape(countModel,len(wavelength))[start:stop,:] = np.einsum('k,jkl->jl',weights,spectra)
    print(f"  averaged {stop} of {countModel} models")
if np.any(emissionDustMean < 0.0):
    sys.exit("the orientation-averaged emission is negative")

# Covering fractions, and the probability of seeing the AGN unobscured averaged over orientation.
coveringFraction           = np.zeros(shape)
probabilityEscape          = np.zeros(shape)
coveringFraction .flat[flat] = library["f2"    ][:]
probabilityEscape.flat[flat] = library["ptype1"][:]
if np.any(np.ptp(coveringFraction,axis=5) > 0.0):
    sys.exit("the covering fraction depends on inclination")
coveringFraction       = coveringFraction[...,0]
probabilityEscapeMean  = np.einsum('k,...k->...',weights,probabilityEscape)

# Write the output.
with h5py.File(fileNameOutput,"w") as output:
    output.attrs["description"] = "CLUMPY library of AGN clumpy dusty torus models, averaged over orientation, converted for use by Galacticus."
    output.attrs["reference"  ] = "Nenkova et al. (2008a), ApJ, 685, 147; Nenkova et al. (2008b), ApJ, 685, 160"
    output.attrs["url"        ] = "https://www.clumpy.org/downloads/clumpy_models_201410_tvavg.hdf5"
    output.attrs["version"    ] = "201410_tvavg"
    output.attrs["md5Source"  ] = md5_checksum(fileNameInput)
    output.attrs["timestamp"  ] = datetime.datetime.now().isoformat()
    try:
        repository = Repo(os.path.dirname(os.path.abspath(__file__)),search_parent_directories=True)
        output.attrs["gitRevisionConverter"] = repository.head.object.hexsha
    except Exception:
        output.attrs["gitRevisionConverter"] = "unknown"
    def dataset(name,data,units,description,compress=False):
        if compress:
            d = output.create_dataset(name,data=data,compression="gzip",compression_opts=9,shuffle=True)
        else:
            d = output.create_dataset(name,data=data)
        d.attrs["units"      ] = units
        d.attrs["description"] = description
    dataset("wavelength"           ,wavelength                       ,"microns","Wavelength.")
    dataset("countCloudsEquatorial",grids["N0" ].astype(float)       ,""       ,"Mean number of clouds along a ray in the equatorial plane, N0.")
    dataset("ratioRadii"           ,grids["Y"  ].astype(float)       ,""       ,"Ratio of outer to inner radius of the torus, Y.")
    dataset("exponentRadial"       ,grids["q"  ].astype(float)       ,""       ,"Exponent, q, of the radial distribution of clouds, proportional to r^-q.")
    dataset("widthAngular"         ,grids["sig"].astype(float)       ,"degrees","Angular width, sigma, of the distribution of clouds about the equatorial plane.")
    dataset("depthOpticalCloudV"   ,grids["tv" ].astype(float)       ,""       ,"Optical depth of a single cloud in the V band, tauV.")
    dataset("coveringFraction"     ,coveringFraction                 ,""       ,"Fraction of the sky covered by the torus as seen from the AGN, [N0,Y,q,sigma,tauV].")
    dataset("probabilityEscapeMean",probabilityEscapeMean            ,""       ,"Probability for the AGN to be seen unobscured, averaged over directions, [N0,Y,q,sigma,tauV].")
    dataset("emissionDustMean"     ,emissionDustMean                 ,""       ,"Emission of the torus (thermal and scattered) averaged over directions, lambda L_lambda per unit AGN luminosity, [N0,Y,q,sigma,tauV,wavelength].",compress=True)
print(f"wrote {fileNameOutput}")
