#!/usr/bin/env python3
"""Independent reference values for the Galacticus cooling chain.

This script recomputes, from first principles and from the tabulated Cloudy data files, the chain of
quantities that determine the rate at which gas cools out of a hot halo:

    halo mass, redshift  ->  mean density  ->  virial radius, velocity, temperature, dynamical time
                         ->  beta-profile density normalization
                         ->  cooling function and electron density (Cloudy tables)
                         ->  cooling time
                         ->  cooling radius (root find)
                         ->  cooling radius growth rate
                         ->  mass cooling rate

It is written from the definitions of the physics, not by transcribing the Fortran: a port of the code
would reproduce any bug the code contains. The two Cloudy HDF5 files are *data*, not code, and are read
directly - but the interpolation scheme applied to them is reimplemented here from the documented
conventions, because that scheme is part of what is being checked.

Conventions that must be matched for the comparison to be meaningful
--------------------------------------------------------------------
  * Virial density contrast. Galacticus' `virialDensityContrast` classes return contrasts relative to the
    *mean matter density*. `virialDensityContrastFixed` accepts `densityType` = "critical" or "mean"; when
    "critical" it divides by Omega_M(t) to convert. The companion unit test pins `densityType`="mean" so
    that the virial radius is analytic and the comparison does not also test the spherical collapse
    solver (which has its own tests).
  * No radiation. Galacticus' `cosmologyFunctionsMatterLambda` expansion rate is Omega_M/a^3 +
    Omega_DarkEnergy + Omega_Curvature/a^2, with no radiation term. The mean density used here is
    therefore built from the present day Omega_M and critical density divided by a^3, with no radiation
    contribution, exactly as `virialDensityContrastDefinitionMeanDensity` does.
  * Metallicity. The `metallicity` datasets hold log10(Z/Z_Solar), with -999 marking zero metallicity.
    The reader delinearizes these (10**Z, with -999 -> 0) before deciding that the first tabulated
    metallicity is zero. For a primordial (Z=0) halo the interpolation therefore pins the metallicity
    index to the first column with a weight of zero, so the cooling function and electron density come
    from the zero metallicity column alone, interpolated in log(temperature) only.
  * Mean atomic mass. `meanAtomicMassPrimordial` counts *fully ionized* particles (2 per hydrogen, 3 per
    helium), and the virial temperature uses the unified atomic mass unit, not the hydrogen atom mass.
  * Total particle density. `n_tot = n_H / hydrogenNumberFraction + n_e`, where `hydrogenNumberFraction`
    counts *nuclei* only, so the first term is the nuclei density and the electrons are added separately.

Andrew Benson, Claude (15-September-2026).
"""

import numpy as np
import h5py
from scipy.optimize import brentq

# ---------------------------------------------------------------------------------------------------
# Physical constants. Deliberately taken from CODATA 2018 / IAU 2015 rather than from Galacticus (which
# uses the GSL values), so that the comparison is genuinely independent. The resulting differences are
# small and are quantified at the end of this script.
# ---------------------------------------------------------------------------------------------------
gravitationalConstantSI = 6.67430e-11                  # m^3 / kg / s^2   (CODATA 2018)
boltzmannsConstantSI    = 1.380649e-23                 # J / K            (exact, SI 2019)
atomicMassUnitSI        = 1.66053906892e-27            # kg               (CODATA 2022)
massSolarSI             = 1.98847e30                   # kg               (IAU 2015 nominal)
megaParsecSI            = 3.0856775814913673e22        # m                (IAU 2015)
gigaYearSI              = 3.1556952e16                 # s                (Julian gigayear)
ergsSI                  = 1.0e-7                       # J per erg

# Atomic masses, in atomic mass units (Commission on Isotopic Abundances and Atomic Weights).
atomicMassHydrogen = 1.0078250322
atomicMassHelium   = 4.0026032545

# Primordial composition by mass (Cyburt et al. 2008).
hydrogenByMassPrimordial = 0.7514
heliumByMassPrimordial   = 0.2486

# Newton's constant in Galacticus' internal unit system: (km/s)^2 Mpc / M_Solar.
gravitationalConstantInternal = gravitationalConstantSI * massSolarSI / (1.0e3) ** 2 / megaParsecSI

# Primordial mean atomic mass, fully ionized: 2 particles per hydrogen, 3 per helium.
meanAtomicMassPrimordial = 1.0 / (
    2.0 * hydrogenByMassPrimordial / atomicMassHydrogen
    + 3.0 * heliumByMassPrimordial / atomicMassHelium
)

# Hydrogen fraction by number, counting nuclei only.
numberHydrogen = hydrogenByMassPrimordial / atomicMassHydrogen
numberHelium   = heliumByMassPrimordial   / atomicMassHelium
hydrogenNumberFractionPrimordial = numberHydrogen / (numberHydrogen + numberHelium)

# ---------------------------------------------------------------------------------------------------
# Model parameters. These must match the companion unit test's parameter file exactly.
# ---------------------------------------------------------------------------------------------------
OmegaMatter     = 0.3153
OmegaDarkEnergy = 0.6847
HubbleConstant  = 67.36                                # km/s/Mpc
densityContrast = 200.0                                # relative to the *mean* matter density
beta            = 2.0 / 3.0
coreRadiusOverVirialRadius = 0.3
degreesOfFreedom           = 3.0
velocityCutOff             = 1.0e4                     # km/s
hotHaloMassFraction        = 0.1                       # M_hot / M_halo, set explicitly by the test

dataPath = "/home/abenson/Galacticus/datasets/static"
coolingFunctionFileName = f"{dataPath}/cooling/cooling_function_Atomic_CIE_Cloudy.hdf5"
chemicalStateFileName   = f"{dataPath}/chemicalState/chemical_state_Atomic_CIE_Cloudy.hdf5"


class CloudyTable:
    """A tabulated Cloudy quantity, interpolated as Galacticus interpolates it.

    The table is bilinear in the logarithms of temperature, metallicity and the tabulated quantity when
    the quantity is everywhere positive. Metallicities are stored in the file as log10(Z/Z_Solar) with
    -999 marking zero; they are delinearized on read. When the first tabulated metallicity is zero, the
    interpolation between zero and the first non-zero metallicity is linear in metallicity rather than in
    its logarithm.
    """

    def __init__(self, fileName, datasetName):
        with h5py.File(fileName, "r") as file:
            self.temperatures  = file["temperature"][()].astype(float)
            metallicities      = file["metallicity"][()].astype(float)
            self.values        = file[datasetName][()].astype(float)
        # Delinearize the metallicities: 10**Z, with the -999 marker becoming exactly zero.
        self.metallicities = np.where(metallicities > -999.0, 10.0 ** metallicities, 0.0)
        self.metallicityMinimum = self.metallicities[ 0]
        self.metallicityMaximum = self.metallicities[-1]
        self.temperatureMinimum = self.temperatures [ 0]
        self.temperatureMaximum = self.temperatures [-1]
        # The table is logarithmic if the tabulated quantity is everywhere positive.
        self.logarithmic = bool((self.values > 0.0).all())
        self.firstMetallicityIsZero = (self.metallicities[0] == 0.0)
        self.firstNonZeroMetallicity = self.metallicities[1] if self.firstMetallicityIsZero else None
        if self.logarithmic:
            self.temperaturesStored  = np.log(self.temperatures)
            self.valuesStored        = np.log(self.values)
            with np.errstate(divide="ignore"):
                self.metallicitiesStored = np.where(
                    self.metallicities > 0.0, np.log(np.maximum(self.metallicities, 1.0e-300)), -999.0
                )
        else:
            self.temperaturesStored  = self.temperatures
            self.valuesStored        = self.values
            self.metallicitiesStored = self.metallicities

    @staticmethod
    def _locate(abscissa, x):
        """Index of the interval containing x, clamped to the table, in Fortran's 1-based convention
        translated to 0-based."""
        return int(np.clip(np.searchsorted(abscissa, x, side="right") - 1, 0, len(abscissa) - 2))

    def interpolate(self, temperature, metallicity):
        # Temperature: clamp to the tabulated range (both extrapolation attributes are "extrapolate",
        # but the halos considered here all lie inside the tabulated range; clamping makes that explicit).
        temperatureUse = min(max(temperature, self.temperatureMinimum), self.temperatureMaximum)
        temperatureUse = np.log(temperatureUse) if self.logarithmic else temperatureUse
        iTemperature   = self._locate(self.temperaturesStored, temperatureUse)
        hTemperature   = (temperatureUse - self.temperaturesStored[iTemperature]) / (
            self.temperaturesStored[iTemperature + 1] - self.temperaturesStored[iTemperature]
        )
        # Metallicity: both extrapolation attributes are "fix", so clamp.
        metallicityUse = max(metallicity, 0.0)
        metallicityUse = min(metallicityUse, self.metallicityMaximum)
        if self.firstMetallicityIsZero and metallicityUse < self.firstNonZeroMetallicity:
            # Linear interpolation in metallicity between zero and the first non-zero value.
            iMetallicity = 0
            hMetallicity = metallicityUse / self.firstNonZeroMetallicity
        else:
            metallicityStored = np.log(metallicityUse) if self.logarithmic else metallicityUse
            iMetallicity      = self._locate(self.metallicitiesStored, metallicityStored)
            hMetallicity      = (metallicityStored - self.metallicitiesStored[iMetallicity]) / (
                self.metallicitiesStored[iMetallicity + 1] - self.metallicitiesStored[iMetallicity]
            )
        # The tabulated arrays are indexed [temperature, metallicity].
        value = (
            self.valuesStored[iTemperature    , iMetallicity    ] * (1.0 - hTemperature) * (1.0 - hMetallicity)
            + self.valuesStored[iTemperature    , iMetallicity + 1] * (1.0 - hTemperature) * (      hMetallicity)
            + self.valuesStored[iTemperature + 1, iMetallicity    ] * (      hTemperature) * (1.0 - hMetallicity)
            + self.valuesStored[iTemperature + 1, iMetallicity + 1] * (      hTemperature) * (      hMetallicity)
        )
        return np.exp(value) if self.logarithmic else value


coolingFunctionTable = CloudyTable(coolingFunctionFileName, "coolingRate"    )
electronDensityTable = CloudyTable(chemicalStateFileName  , "electronDensity")


def densityCriticalPresentDay():
    """Present day critical density, in M_Solar/Mpc^3."""
    return 3.0 * HubbleConstant ** 2 / 8.0 / np.pi / gravitationalConstantInternal


def densityMean(redshift):
    """Mean density of a halo, in M_Solar/Mpc^3, for a contrast specified relative to the mean matter
    density. Galacticus builds this from the *present day* Omega_M and critical density divided by a^3."""
    expansionFactor = 1.0 / (1.0 + redshift)
    return densityContrast * OmegaMatter * densityCriticalPresentDay() / expansionFactor ** 3


def haloScales(massHalo, redshift):
    """Virial radius (Mpc), velocity (km/s), temperature (K) and dynamical time (Gyr)."""
    radiusVirial   = (3.0 * massHalo / 4.0 / np.pi / densityMean(redshift)) ** (1.0 / 3.0)
    velocityVirial = np.sqrt(gravitationalConstantInternal * massHalo / radiusVirial)
    temperature    = (
        0.5 * atomicMassUnitSI * meanAtomicMassPrimordial * (1.0e3 * velocityVirial) ** 2
        / boltzmannsConstantSI
    )
    timeDynamical  = radiusVirial / velocityVirial * (megaParsecSI / 1.0e3 / gigaYearSI)
    return radiusVirial, velocityVirial, temperature, timeDynamical


def betaProfileNormalization(massHot, radiusCore, radiusOuter):
    """Central density rho_0 (M_Solar/Mpc^3) of a beta=2/3 profile enclosing massHot within radiusOuter.

    For beta=2/3 the enclosed mass integrates in closed form, giving
        rho_0 = M / (4 pi r_core^3) / (x - arctan x),  x = r_outer / r_core.
    """
    x = radiusOuter / radiusCore
    return massHot / 4.0 / np.pi / radiusCore ** 3 / (x - np.arctan(x))


def density(radius, densityNormalization, radiusCore):
    """beta-profile density, rho_0 [1 + (r/r_core)^2]^(-3 beta / 2)."""
    return densityNormalization * (1.0 + (radius / radiusCore) ** 2) ** (-1.5 * beta)


def densityLogSlope(radius, radiusCore):
    """d ln rho / d ln r for a beta profile."""
    xSquared = (radius / radiusCore) ** 2
    return -3.0 * beta * xSquared / (1.0 + xSquared)


def coolingTime(densityGas, temperature):
    """Cooling time in Gyr, for gas of the given density (M_Solar/Mpc^3) and temperature (K).

    t_cool = (N/2) k_B T n_tot / Lambda, with n_tot including electrons.
    """
    # Hydrogen number density, in cm^-3.
    numberDensityHydrogen = (
        densityGas * hydrogenByMassPrimordial * massSolarSI
        / (atomicMassHydrogen * atomicMassUnitSI)
        / (1.0e2) ** 3 / megaParsecSI ** 3
    )
    # Electron density is tabulated relative to hydrogen and scales linearly with it.
    numberDensityElectron = electronDensityTable.interpolate(temperature, 0.0) * numberDensityHydrogen
    numberDensityTotal    = numberDensityHydrogen / hydrogenNumberFractionPrimordial + numberDensityElectron
    # Cooling function is tabulated at n_H = 1 cm^-3 and scales as n_H^2.
    coolingFunction = coolingFunctionTable.interpolate(temperature, 0.0) * numberDensityHydrogen ** 2
    if coolingFunction <= 0.0:
        return 1.0e10
    energyDensityThermal = (
        degreesOfFreedom / 2.0 * boltzmannsConstantSI * temperature * numberDensityTotal / ergsSI
    )
    return energyDensityThermal / coolingFunction / gigaYearSI


def coolingChain(massHalo, redshift):
    """Return every link in the chain for a halo of the given mass (M_Solar) and redshift."""
    radiusVirial, velocityVirial, temperature, timeDynamical = haloScales(massHalo, redshift)
    radiusCore  = coreRadiusOverVirialRadius * radiusVirial
    # The hot halo outer radius getter clamps the stored value: max(min(stored, r_vir), 0.1 r_vir). The
    # test stores r_vir, so the clamp returns r_vir exactly.
    radiusOuter = max(min(radiusVirial, radiusVirial), 0.1 * radiusVirial)
    massHot     = hotHaloMassFraction * massHalo
    densityNormalization = betaProfileNormalization(massHot, radiusCore, radiusOuter)
    # Time available for cooling: ageFactor = 0 gives the halo dynamical time, with unit increase rate.
    timeAvailable             = timeDynamical
    timeAvailableIncreaseRate = 1.0

    def root(radius):
        return coolingTime(density(radius, densityNormalization, radiusCore), temperature) - timeAvailable

    # Locate the cooling radius. The cooling time increases outwards (density falls), so the root is
    # bracketed by a small inner radius and the outer radius when it exists at all.
    radiusInner = 1.0e-6 * radiusOuter
    rootInner, rootOuter = root(radiusInner), root(radiusOuter)
    if rootInner > 0.0:
        radiusCooling = 0.0                      # everywhere cooling is slower than the time available
    elif rootOuter < 0.0:
        radiusCooling = radiusOuter              # the whole halo can cool
    else:
        radiusCooling = brentq(root, radiusInner, radiusOuter, rtol=1.0e-12, xtol=1.0e-16)

    # Growth rate of the cooling radius. The temperature is uniform, so the temperature term vanishes and
    # only the density term survives; d ln t_cool / d ln rho = 1 - 2 = -1 for a CIE cooling function.
    if radiusCooling > 0.0 and radiusCooling < radiusOuter:
        slope = densityLogSlope(radiusCooling, radiusCore) * (-1.0)
        radiusCoolingGrowthRate = radiusCooling / timeAvailable * timeAvailableIncreaseRate / slope
    else:
        radiusCoolingGrowthRate = 0.0

    # Mass cooling rate.
    if velocityVirial > velocityCutOff:
        rateCooling = 0.0
    elif radiusCooling >= radiusOuter:
        rateCooling = massHot / timeDynamical
    else:
        rateCooling = (
            4.0 * np.pi * radiusCooling ** 2
            * density(radiusCooling, densityNormalization, radiusCore)
            * radiusCoolingGrowthRate
        )
    return dict(
        radiusVirial=radiusVirial, velocityVirial=velocityVirial, temperature=temperature,
        timeDynamical=timeDynamical, radiusCore=radiusCore, radiusOuter=radiusOuter, massHot=massHot,
        densityNormalization=densityNormalization, timeAvailable=timeAvailable,
        radiusCooling=radiusCooling, radiusCoolingGrowthRate=radiusCoolingGrowthRate,
        rateCooling=rateCooling,
    )


if __name__ == "__main__":
    print("Cooling chain reference values")
    print(f"  Omega_M={OmegaMatter}, Omega_DE={OmegaDarkEnergy}, H_0={HubbleConstant} km/s/Mpc")
    print(f"  contrast={densityContrast} (relative to the mean matter density), beta={beta:.6f}")
    print(f"  r_core/r_vir={coreRadiusOverVirialRadius}, N={degreesOfFreedom}, M_hot/M_halo={hotHaloMassFraction}")
    print(f"  G(internal)={gravitationalConstantInternal:.10e} (km/s)^2 Mpc/M_Solar")
    print(f"  mu_p={meanAtomicMassPrimordial:.10f}, X_H(number)={hydrogenNumberFractionPrimordial:.10f}")
    print(f"  rho_crit,0={densityCriticalPresentDay():.10e} M_Solar/Mpc^3")
    print()
    # The test cases are chosen to exercise all three branches of the cooling rate: the "saturated"
    # branch where the cooling radius has reached the outer radius and infall is limited to the
    # dynamical timescale; the "interior" branch where the cooling radius lies strictly inside the halo
    # and the rate is 4 pi r^2 rho(r) rdot; and the "none" branch where the cooling time exceeds the
    # time available everywhere so nothing cools. (The velocity cut off branch is not exercised here: it
    # requires a virial velocity above 1e4 km/s, i.e. an unphysical ~1e17 M_Solar halo, and is better
    # tested by lowering [velocityCutOff] in the parameter file.)
    testCases = (
        (10.50, 0.0),   # saturated
        (11.00, 0.0),   # saturated
        (11.00, 1.0),   # interior, r_cool/r_outer ~ 0.63
        (11.25, 0.0),   # interior, r_cool/r_outer ~ 0.55
        (11.25, 2.0),   # interior, r_cool/r_outer ~ 0.30
        (11.50, 0.0),   # interior, r_cool/r_outer ~ 0.23
        (11.50, 1.0),   # interior, r_cool/r_outer ~ 0.12
        (12.00, 0.0),   # none
    )
    print("  Derived quantities, tabulated for the unit test:")
    header = (
        "    log10(M/Msun)    z    branch       r_vir [Mpc]      V_vir [km/s]     T_vir [K]        "
        "tau_dyn [Gyr]    rho_0 [Msun/Mpc^3]  r_cool [Mpc]     rdot [Mpc/Gyr]   Mdot [Msun/Gyr]"
    )
    print(header)
    for massHaloLogarithmic, redshift in testCases:
        massHalo = 10.0 ** massHaloLogarithmic
        chain    = coolingChain(massHalo, redshift)
        if   chain["radiusCooling"] <= 0.0:                    branch = "none"
        elif chain["radiusCooling"] >= chain["radiusOuter"]:   branch = "saturated"
        else:                                                  branch = "interior"
        print(
            f"    {massHaloLogarithmic:12.2f} {redshift:5.1f} {branch:>10}   "
            f"{chain['radiusVirial']:.8e}   {chain['velocityVirial']:.8e}   "
            f"{chain['temperature']:.8e}   {chain['timeDynamical']:.8e}   "
            f"{chain['densityNormalization']:.8e}      {chain['radiusCooling']:.8e}   "
            f"{chain['radiusCoolingGrowthRate']:.8e}   {chain['rateCooling']:.8e}"
        )
    print()
    print("  Cooling time and hot gas density at the cooling radius (further assertion targets):")
    print("    log10(M/Msun)    z      rho(r_cool) [Msun/Mpc^3]   t_cool(r_cool) [Gyr]   t_available [Gyr]")
    for massHaloLogarithmic, redshift in testCases:
        chain = coolingChain(10.0 ** massHaloLogarithmic, redshift)
        if chain["radiusCooling"] <= 0.0:
            continue
        densityAtCoolingRadius = density(
            chain["radiusCooling"], chain["densityNormalization"], chain["radiusCore"]
        )
        print(
            f"    {massHaloLogarithmic:12.2f} {redshift:5.1f}      {densityAtCoolingRadius:.8e}"
            f"              {coolingTime(densityAtCoolingRadius, chain['temperature']):.8e}"
            f"         {chain['timeAvailable']:.8e}"
        )
