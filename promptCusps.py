#!/usr/bin/env python3
import cusp_halo_relation

# Compute properties of prompt cusps using Sten Delos' `cusp_halo_relation` Python module
# (https://github.com/delos/cusp-halo-relation). Used to validate the Galacticus implementation of this model in the test code
# `tests.prompt_cusps.F90` (https://github.com/galacticusorg/galacticus/blob/master/source/tests.prompt_cusps.F90).
# Andrew Benson (24-June-2025)

# Construct the default model with a 10keV WDM particle mass.
model = cusp_halo_relation.CuspHaloWDM(mX=10.0)

# Compute the power spectrum integrals σ₀ and σ₂ at z=0 and z=8.
print('\nPower spectrum integrals:')
print(f'   σ₀(z=0) = {model.sigma0(1.0/(1.0+0.0)):.5e}')
print(f'   σ₀(z=8) = {model.sigma0(1.0/(1.0+8.0)):.5e}')
print(f'   σ₂(z=0) = {model.sigma2(1.0/(1.0+0.0)):.5e}')
print(f'   σ₂(z=8) = {model.sigma2(1.0/(1.0+8.0)):.5e}')

# Compute properties of the prompt cusp in a reference halo.
massHalo     = 3.0e8
redshiftHalo = 1.5
amplitudeCusp            = model.A_at_z(M=massHalo,z=redshiftHalo)
massCusp            = model.m_at_z(M=massHalo,z=redshiftHalo)
concentration            = model.c_at_z(           z=redshiftHalo)
densityVirial      = 200.*model.rhoCrit_at_z(z=redshiftHalo)     
radiusScale, densityScale     = cusp_halo_relation.cuspNFW.scale_from_c(concentration,massHalo,amplitudeCusp,densityVirial)
y            = amplitudeCusp/densityScale/radiusScale**1.5
print('\nCusp properties in reference halo:')
print(f'   rₛ = {radiusScale   :.5e} Mpc'     )
print(f'   A  = {amplitudeCusp:.5e} M☉/Mpc¹ॱ⁵')
print(f'   m  = {massCusp     :.5e} M☉'       )
print(f'   y  = {y            :.5e}'          )
