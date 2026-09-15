#!/usr/bin/env python3
# Reference values for halo mass definitions, virial density contrasts, and output time conversions in Galacticus, computed
# independently using colossus and astropy. Used to validate `source/tests/mass_definitions_output_times.F90`.
#
#  * Virial density contrast: Galacticus' `virialDensityContrast` classes return contrasts relative to the *mean matter density*
#    (see `virialDensityContrastFixed`, which divides by Omega_M(t) when its contrast is specified relative to the critical
#    density). Bryan & Norman's (1998) fitting function, and colossus' `mass_so.deltaVir()`, are relative to the *critical*
#    density. The two therefore differ by a factor Omega_M(z).
#  * Mass definitions: `Dark_Matter_Profile_Mass_Definition` finds the radius enclosing a given mean density and the mass within
#    it, for the node's dark matter profile. For an NFW profile of given (M200c, c200c) this is exactly what colossus'
#    `mass_defs.changeMassDefinition` computes. Note colossus works in Msun/h and kpc/h.
#  * Output times: the `outputTimes` classes convert between redshift and cosmic time via the cosmology functions, which astropy
#    reproduces for a flat LambdaCDM model.
# Andrew Benson, Claude (15-September-2026)
import numpy as np
from colossus.cosmology import cosmology as colossusCosmology
from colossus.halo import mass_defs, mass_so
from astropy.cosmology import FlatLambdaCDM
import astropy.units as u

# Cosmological parameters. These must match those used by the Fortran unit test exactly.
OmegaMatter    = 0.2815
OmegaBaryon    = 0.0465
OmegaDarkEnergy= 0.7185
HubbleConstant = 69.3
temperatureCMB = 2.78
hubbleH        = HubbleConstant/100.0

# Halo used for the mass definition tests.
massHalo200c   = 1.0e12                                                        # M☉, defined at a contrast of 200 x critical
concentration  = 5.0
redshiftHalo   = 0.0

# Galacticus' `cosmologyFunctionsMatterLambda` expansion rate is Omega_M/a^3 + Omega_DarkEnergy + Omega_Curvature/a^2, with no
# radiation term. Radiation is therefore excluded from both reference codes: colossus is given Tcmb0=0 and astropy Tcmb0=0. This
# matters: with Tcmb0=2.78 colossus' Omega_M(z) differs from the pure matter plus dark energy value by 4.8e-4 at z=1 and 1.3e-3
# at z=3, which would swamp the tolerances used here.
colossus = colossusCosmology.setCosmology(
    'galacticusTest',
    **{'flat': True, 'H0': HubbleConstant, 'Om0': OmegaMatter, 'Ob0': OmegaBaryon, 'sigma8': 0.8, 'ns': 0.96, 'Tcmb0': 0.0}
)
astropyCosmology = FlatLambdaCDM(H0=HubbleConstant, Om0=OmegaMatter, Tcmb0=0.0, Neff=0.0)

def omegaMatterEpochal(redshift):
    """Omega_M(z) for a flat matter plus dark energy cosmology, as Galacticus computes it."""
    expansionFactor = 1.0/(1.0+redshift)
    return OmegaMatter/expansionFactor**3/(OmegaMatter/expansionFactor**3+OmegaDarkEnergy)

def densityContrastBryanNorman(redshift):
    """Bryan & Norman (1998) virial density contrast relative to the critical density, for a flat universe."""
    x = omegaMatterEpochal(redshift)-1.0
    return 18.0*np.pi**2+82.0*x-39.0*x**2

if __name__ == "__main__":
    print(f"Cosmology: OmegaMatter={OmegaMatter}, OmegaDarkEnergy={OmegaDarkEnergy}, H0={HubbleConstant}, h={hubbleH}")

    print("\nVirial density contrast, relative to the mean matter density (Galacticus' convention):")
    print("  z, Omega_M(z), Delta_critical [Bryan & Norman 1998], Delta_mean = Delta_critical/Omega_M(z), colossus deltaVir")
    for redshift in (0.0, 1.0, 3.0):
        omegaMatter      = omegaMatterEpochal        (redshift)
        contrastCritical = densityContrastBryanNorman(redshift)
        print(f"  {redshift:4.1f} {omegaMatter:.10f} {contrastCritical:.10f} {contrastCritical/omegaMatter:.10e} {mass_so.deltaVir(redshift):.10f}")

    print(f"\nHalo: M200c={massHalo200c:.3e} M☉, c200c={concentration}, z={redshiftHalo}")
    radius200c = mass_so.M_to_R(massHalo200c*hubbleH,redshiftHalo,'200c')/hubbleH/1.0e3
    print(f"  R200c            = {radius200c:.10e} Mpc")
    print(f"  scale radius     = {radius200c/concentration:.10e} Mpc")
    print("  mass definition conversions (NFW profile held fixed):")
    for definition in ('200m','vir','500c'):
        massOut, radiusOut, concentrationOut = mass_defs.changeMassDefinition(massHalo200c*hubbleH,concentration,redshiftHalo,'200c',definition)
        # Contrast relative to the mean matter density, as Galacticus defines it.
        contrastMean = mass_so.densityThreshold(redshiftHalo,definition)/(colossus.Om(redshiftHalo)*mass_so.densityThreshold(redshiftHalo,'1c'))
        print(f"    {definition:4s}: Delta_mean={contrastMean:.10e} M={massOut/hubbleH:.10e} M☉ R={radiusOut/hubbleH/1.0e3:.10e} Mpc c={concentrationOut:.8f}")

    print("\nOutput time conversions (flat matter plus dark energy, no radiation):")
    print("  z -> cosmic time [Gyr]")
    for redshift in (0.0, 0.5, 1.0, 3.0, 9.0):
        print(f"  {redshift:5.2f} -> {astropyCosmology.age(redshift).to(u.Gyr).value:.10e}")
    print("  time [Gyr] -> z")
    from astropy.cosmology import z_at_value
    for time in (1.0, 5.0, 13.0):
        print(f"  {time:5.2f} -> {z_at_value(astropyCosmology.age,time*u.Gyr).value:.10e}")
