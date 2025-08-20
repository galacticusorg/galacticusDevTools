#!/usr/bin/env python3
import numpy as np
from cusp_halo_relation import CuspHaloWDM, cuspNFW

# Compute properties of prompt cusps using Sten Delos' `cusp_halo_relation` Python module
# (https://github.com/delos/cusp-halo-relation). Used to validate the Galacticus implementation of this model in the test code
# `tests.prompt_cusps.F90` (https://github.com/galacticusorg/galacticus/blob/master/source/tests.prompt_cusps.F90).
# Andrew Benson (24-June-2025)

# Construct the default model with a 10keV WDM particle mass.
model = CuspHaloWDM(mX=10.0,OmegaM=0.3089,OmegaB=0.04886,n_s=0.9649,sigma8=0.8086539)

# Compute the power spectrum integrals σ₀ and σ₂ at z=0 and z=8.
print('\nPower spectrum integrals:')
print(f'   σ₀(z=0) = {model.sigma0(1.0/(1.0+0.0)):.5e}')
print(f'   σ₀(z=8) = {model.sigma0(1.0/(1.0+8.0)):.5e}')
print(f'   σ₂(z=0) = {model.sigma2(1.0/(1.0+0.0)):.5e}')
print(f'   σ₂(z=8) = {model.sigma2(1.0/(1.0+8.0)):.5e}')

# Compute properties of the prompt cusp in a reference halo.
massHalo                   = 3.0e8
redshiftHalo               = 1.5
amplitudeCusp              =       model  .      A_at_z(M=massHalo,z      =redshiftHalo )
massCusp                   =       model  .      m_at_z(M=massHalo,z      =redshiftHalo )
concentration              =       model  .      c_at_z(           z      =redshiftHalo )
densityVirial              = 200.0*model  .rhoCrit_at_z(           z      =redshiftHalo )
radiusVirial               =       cuspNFW.R_from_M    (M=massHalo,rho_vir=densityVirial)
radiusScale , densityScale =       cuspNFW.scale_from_c(concentration,massHalo    ,amplitudeCusp,densityVirial)
radiusMinus2               =       cuspNFW.r2_from_rs  (radiusScale  ,densityScale,amplitudeCusp              )
y                          = amplitudeCusp/densityScale/radiusScale**1.5

# Determine virial properties of the halo under Galacticus' definitions (i.e. spherical collapse for the virial density
# contrast). The virial radius is chosen to achieve the required virial density as reported by Galacticus.
radiusVirialGalacticus     = 8.6803e-3
massVirialGalacticus       = cuspNFW.mass(radiusVirialGalacticus,radiusScale,densityScale,amplitudeCusp)
densityVirialGalacticus    = 3.0*massVirialGalacticus/4.0/np.pi/radiusVirialGalacticus**3
print('\nGalacticus properties in reference halo:')
print(f'   rᵥ  = {radiusVirialGalacticus :.5e} Mpc'    )
print(f'   mᵥ  = {massVirialGalacticus   :.5e} M☉'     )
print(f'   ρᵥ  = {densityVirialGalacticus:.5e} M☉/Mpc³')

# Report on cusp properties.
print('\nCusp properties in reference halo:')
print(f'   ρᵥ  = {densityVirial :.5e} M☉/Mpc³' )
print(f'   rᵥ  = {radiusVirial  :.5e} Mpc'     )
print(f'   rₛ  = {radiusScale   :.5e} Mpc'     )
print(f'   r₋₂ = {radiusMinus2  :.5e} Mpc'     )
print(f'   ρₛ  = {densityScale  :.5e} M☉/Mpc³' )
print(f'   A   = {amplitudeCusp:.5e} M☉/Mpc¹ॱ⁵')
print(f'   m   = {massCusp     :.5e} M☉'       )
print(f'   y   = {y            :.5e}'          )
