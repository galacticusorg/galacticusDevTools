#!/usr/bin/env python3
import numpy as np
import h5py
import os
import hashlib
import datetime
import urllib.request
from astropy.io import fits
from git import Repo

# Create a file of emission line fluxes for star forming galaxies using the SDSS DR8 value added catalogs.
# Andrew Benson (17-June-2025)

# See https://www.sdss4.org/dr14/spectro/galaxy_mpajhu/ for a description of the catalogs.

# Function to compute the md5sum of a file.
def md5_checksum(file_path):
    m = hashlib.md5()
    with open(file_path, 'rb') as file:
        while True:
            data = file.read(8192)  # Read in chunks to handle large files
            if not data:
                break
            m.update(data)
    return m.hexdigest()

# Download the SDSS data files.
for fileName in "galSpecExtra-dr8.fits", "galSpecLine-dr8.fits":
    if not os.path.isfile(fileName):
        try:
            urllib.request.urlretrieve("https://data.sdss.org/sas/dr8/common/sdss-spectro/redux/"+fileName, fileName)
        except urllib.request.HTTPError as e:
            print(f"Failed to download stellar populations file: HTTP Error: {e.code} - {e.reason}")
        except Exception as e:
            print(f"Failed to download stellar populations file: {e}") 

# Load the data.
extraFile = fits.open('galSpecExtra-dr8.fits')
extra     = extraFile[1].data
linesFile = fits.open('galSpecLine-dr8.fits')
lines     = linesFile[1].data

# Select star forming galaxies.
selectSF  = extra['bptclass'] == 1

# Select AGN galaxies.
selectAGN = extra['bptclass'] == 4

# Get git revision.
repo         = Repo(".")
lastRevision = repo.head.object.hexsha

# Star forming galaxies.

# Extract required lines.
fluxes = {}
fluxes['balmerAlpha6565'] = lines['h_alpha_flux'  ][selectSF]
fluxes['balmerBeta4863' ] = lines['h_beta_flux'   ][selectSF]
fluxes['oxygenII3727'   ] = lines['oii_3726_flux' ][selectSF]
fluxes['oxygenIII5008'  ] = lines['oiii_5007_flux'][selectSF]
fluxes['nitrogenII6585' ] = lines['nii_6584_flux' ][selectSF]
fluxes['sulfurII6718'   ] = lines['sii_6717_flux' ][selectSF]
fluxes['sulfurII6733'   ] = lines['sii_6731_flux' ][selectSF]

# Output to HDF5.
output = h5py.File(os.environ.get('GALACTICUS_DATA_PATH')+'/static/observations/emissionLines/emissionLineFluxesStarFormingSDSSDR8.hdf5','w')
output.attrs['description'         ] = "Emission line fluxes of star forming galaxies from the SDSS DR8 catalog."
output.attrs['referenceURL'        ] = "https://www.sdss4.org/dr14/spectro/galaxy_mpajhu/"
output.attrs['createdBy'           ] = "https://github.com/galacticusorg/galacticusDevTools/blob/"+lastRevision+"/extractSDSSBPTData.py"
output.attrs['timeStamp'           ] = str(datetime.datetime.now())
output.attrs['galSpecExtraChecksum'] = md5_checksum('galSpecExtra-dr8.fits')
output.attrs['galSpecLineChecksum' ] = md5_checksum('galSpecLine-dr8.fits' )
for lineName in fluxes:
    output.create_dataset(lineName,data=fluxes[lineName])

# AGN
    
# Extract required lines.
fluxes = {}
fluxes['balmerAlpha6565'] = lines['h_alpha_flux'  ][selectAGN]
fluxes['balmerBeta4863' ] = lines['h_beta_flux'   ][selectAGN]
fluxes['oxygenII3727'   ] = lines['oii_3726_flux' ][selectAGN]
fluxes['oxygenIII5008'  ] = lines['oiii_5007_flux'][selectAGN]
fluxes['nitrogenII6585' ] = lines['nii_6548_flux' ][selectAGN]
fluxes['sulfurII6718'   ] = lines['sii_6717_flux' ][selectAGN]
fluxes['sulfurII6733'   ] = lines['sii_6731_flux' ][selectAGN]

# Output to HDF5.
output = h5py.File(os.environ.get('GALACTICUS_DATA_PATH')+'/static/observations/emissionLines/emissionLineFluxesAGNSDSSDR8.hdf5','w')
output.attrs['description'         ] = "Emission line fluxes of AGN from the SDSS DR8 catalog."
output.attrs['referenceURL'        ] = "https://www.sdss4.org/dr14/spectro/galaxy_mpajhu/"
output.attrs['createdBy'           ] = "https://github.com/galacticusorg/galacticusDevTools/blob/"+lastRevision+"/extractSDSSBPTData.py"
output.attrs['timeStamp'           ] = str(datetime.datetime.now())
output.attrs['galSpecExtraChecksum'] = md5_checksum('galSpecExtra-dr8.fits')
output.attrs['galSpecLineChecksum' ] = md5_checksum('galSpecLine-dr8.fits' )
for lineName in fluxes:
    output.create_dataset(lineName,data=fluxes[lineName])
