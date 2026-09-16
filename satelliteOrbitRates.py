#!/usr/bin/env python3
"""Independent reference values for the rates which drive satellite orbital evolution in Galacticus.

Plan item 9 asks for orbital decay time and bound mass from an integrated orbit. Those are the
*outcome* of two rates, and this script covers the rates themselves, evaluated pointwise over a grid
of phase-space configurations:

    host NFW halo, satellite NFW halo,       ->  velocity dispersion of the host (isotropic Jeans)
    satellite position and velocity          ->  Chandrasekhar (1943) dynamical friction acceleration
                                             ->  King (1962) tidal radius
                                             ->  Zentner et al. (2005) tidal mass loss rate

Splitting the item this way follows the shape of the stellar-population work: verify the rates first,
where a physics defect would live, then the assembly of those rates into the orbital ODE separately.
A comparison of an integrated orbit alone cannot tell a wrong rate from a wrongly assembled one.

It is written from the definitions, not by transcribing the Fortran.

What is verified, and what is not
---------------------------------
The two rates and the host velocity dispersion are reimplemented here from the papers. The King (1962)
tidal radius is *also* reimplemented, but only because the mass-loss rate needs it: that radius is the
derivation session's item and has its own independent reference in `referenceKing1962.py`. Treat any
disagreement in the tidal radius as theirs, not this script's.

Conventions that must be matched for the comparison to be meaningful
--------------------------------------------------------------------
  * Units. Galacticus' internal system throughout: masses in Msun, lengths in Mpc, velocities in km/s,
    with G = 4.3011827419096073e-9 Mpc (km/s)^2 / Msun. Working consistently in these units means the
    orbital frequency and the tidal tensor are both in (km/s/Mpc)^2 and need no conversion factors -
    the `kilo * gigaYear / megaParsec` factors scattered through the Fortran are converting to Gyr^-1
    for the ODE, and are not part of the physics.
  * The velocity dispersion entering the Chandrasekhar integral is the host's 1D dispersion from its
    kinematics distribution. For an isotropic NFW that is the isotropic Jeans solution,
    sigma^2(r) = (1/rho) Int_r^inf rho(r') G M(<r') / r'^2 dr', which is what is used here.
  * The Chandrasekhar integral carries a suppression factor min(1, M_sat(<r)/M_sat) which is on by
    default (`chandrasekharIntegralSuppressExtendedMass`). It exists to stop a very extended subhalo
    near its host's center receiving an enormous acceleration; it is applied here.
  * The Chandrasekhar term is cut off at X = v / (sqrt(2) sigma) > 10, above which Galacticus drops the
    erf factor entirely rather than evaluating it.
  * Zentner et al. (2005) uses the *larger* of the angular and radial orbital frequencies, to stay well
    behaved for purely circular and purely radial orbits alike, and multiplies the mass outside the
    tidal radius by an efficiency over a timescale which is either the orbital period or a dynamical
    time at the tidal radius, selected by `useDynamicalTimeScale`.
  * King (1962) sets the tidal radius to the radius enclosing a mean density
    rho_tidal = (3 / 4 pi) (epsilon omega^2 - T_dominant) / G, where T is the host's tidal tensor at the
    satellite's position. For a spherical host the dominant (most stretching) eigenvalue is radial,
    T_rr = G (2 M(<r) / r^3 - 4 pi rho(r)).

Output
------
With no arguments the script prints the reference table. `--fortran` emits it as Fortran array
initializers. `--verify` reports internal checks of the pieces against limits where they have known
closed forms.

Andrew Benson, Claude (16-September-2026).
"""

import argparse
import numpy as np
from scipy.integrate import quad
from scipy.optimize import brentq
from scipy.special import erf

# Newton's constant in Galacticus' internal unit system: Msun, Mpc, km/s.
gravitationalConstant = 4.3011827419096073e-9

# Conversion from km/s/Mpc to Gyr^-1. Galacticus applies this to both rates so that they are per unit
# time for the ODE solver; the physics is done in km/s and Mpc throughout and only the final result is
# converted. This is the `kilo * gigaYear / megaParsec` factor which appears in the Fortran.
kilo = 1.0e3
gigaYear = 3.155695200e16
megaParsec = 3.0856775809623245e22
toPerGigaYear = kilo * gigaYear / megaParsec

# Cosmology: Planck 2018, matching the companion test's parameter file.
omegaMatter = 0.3153
omegaBaryon = 0.0493

# The fraction of a halo's mass held by its dark matter profile.
#
# This is not a modelling choice here; it is a convention of the code which had to be measured. Galacticus offers
# two normalizations of the same halo, and which one a calculation reaches for matters:
#
#   * `node%massDistribution()`, and `(componentTypeDarkHalo, massTypeDark)`, are normalized to
#     `basic%mass() x (1 - Omega_b/Omega_M)` - the dark matter actually present once baryons are removed.
#   * `(componentTypeDarkMatterOnly, massTypeDark)` is normalized to the full `basic%mass()`.
#
# Measured directly for a 10^10 Msun satellite: 8.4364e9, 8.4364e9 and 1.0000e10 respectively, against a bound
# mass of 1.0000e10.
#
# The satellite's *bound* mass is a total: `satelliteMassBoundInitializorBasicMass` sets it to the basic mass. So
# any expression combining a bound mass with a profile mass must use the dark-matter-only profile, or it mixes the
# two normalizations. Two places in the code did mix them, and both are now fixed; this script follows the fixed
# code. Which profile each quantity below uses is stated at its call site, because it is not guessable.
fractionDarkMatter = 1.0 - omegaBaryon / omegaMatter


class ProfileNFW:
    """An NFW profile normalized to a given mass within a given virial radius."""

    def __init__(self, mass, radiusVirial, concentration):
        self.mass = mass
        self.radiusVirial = radiusVirial
        self.concentration = concentration
        self.radiusScale = radiusVirial / concentration
        self.densityNormalization = mass / (4.0 * np.pi * self.radiusScale**3 * self._mu(concentration))

    @staticmethod
    def _mu(x):
        """The NFW mass function mu(x) = ln(1+x) - x/(1+x).

        Evaluated as a series for small x. The closed form is catastrophically cancelling there - both
        terms tend to x while their difference tends to x^2/2 - and returns a *negative* value once x
        falls below about 1e-8, which silently corrupts any enclosed mass or mean density evaluated at
        a small radius. The series is
            mu(x) = x^2/2 - 2x^3/3 + 3x^4/4 - ...
        whose neglected term is below 1e-16 relative for x < 1e-4."""
        x = np.asarray(x, dtype=float)
        small = x < 1.0e-4
        return np.where(
            small,
            x**2 / 2.0 - 2.0 * x**3 / 3.0 + 3.0 * x**4 / 4.0,
            np.log(1.0 + np.where(small, 1.0, x)) - np.where(small, 1.0, x) / (1.0 + np.where(small, 1.0, x)),
        )

    def density(self, radius):
        x = radius / self.radiusScale
        return self.densityNormalization / (x * (1.0 + x) ** 2)

    def massEnclosed(self, radius):
        return self.mass * self._mu(radius / self.radiusScale) / self._mu(self.concentration)

    def velocityDispersion(self, radius):
        """1D velocity dispersion from the isotropic Jeans equation,

            rho(r) sigma^2(r) = Int_r^inf rho(r') G M(<r') / r'^2 dr'.

        The integral converges: rho falls as r^-3 while M grows only logarithmically."""
        def integrand(radiusPrime):
            return self.density(radiusPrime) * gravitationalConstant * self.massEnclosed(radiusPrime) / radiusPrime**2
        # Integrate in the logarithm, which is far better conditioned over the many decades involved.
        def integrandLog(logRadius):
            radiusPrime = np.exp(logRadius)
            return integrand(radiusPrime) * radiusPrime
        value, _ = quad(integrandLog, np.log(radius), np.log(1.0e4 * self.radiusVirial), limit=200)
        return np.sqrt(value / self.density(radius))

    def tidalTensorRadial(self, radius):
        """The dominant (radial, most stretching) eigenvalue of the tidal tensor of a spherical
        distribution: T_rr = G (2 M(<r) / r^3 - 4 pi rho(r)), in (km/s/Mpc)^2."""
        return gravitationalConstant * (
            2.0 * self.massEnclosed(radius) / radius**3 - 4.0 * np.pi * self.density(radius)
        )


def accelerationDynamicalFriction(host, satellite, massSatellite, position, velocity, logarithmCoulomb,
                                  suppressExtendedMass=True):
    """Chandrasekhar (1943) dynamical friction acceleration, in km/s/Gyr.

        a = 4 pi G^2 M ln(Lambda) * I,   I = -rho(r) v / |v|^3 * [erf(X) - 2 X exp(-X^2)/sqrt(pi)]

    with X = |v| / (sqrt(2) sigma(r)), optionally suppressed by min(1, M_sat(<r)/M_sat)."""
    radius = np.linalg.norm(position)
    speed = np.linalg.norm(velocity)
    if speed <= 0.0:
        return np.zeros(3)
    density = host.density(radius)
    if density <= 0.0:
        return np.zeros(3)
    dispersion = host.velocityDispersion(radius)
    x = speed / dispersion / np.sqrt(2.0) if dispersion > 0.0 else np.inf
    integral = -density * np.asarray(velocity) / speed**3
    # Galacticus drops the erf factor above X = 10 rather than evaluating it; there it is unity to
    # within 1e-44, so this is a statement about cost, not accuracy.
    if x <= 10.0:
        integral = integral * (erf(x) - 2.0 * x * np.exp(-(x**2)) / np.sqrt(np.pi))
    if suppressExtendedMass:
        # `satellite` here is the dark-matter-only profile, normalized to the same total mass as `massSatellite`, so
        # this factor reaches unity for a satellite lying well inside the radius sampled. Before the fix in
        # `Chandrasekhar1943.F90` the code used the baryon-corrected profile here and the factor saturated at
        # `fractionDarkMatter` instead, suppressing every satellite by the baryon fraction however compact it was.
        integral = integral * min(1.0, satellite.massEnclosed(radius) / massSatellite)
    # The physics above is in (km/s)^2/Mpc; convert to km/s/Gyr as Galacticus does.
    return 4.0 * np.pi * gravitationalConstant**2 * logarithmCoulomb * massSatellite * integral * toPerGigaYear


def radiusTidalKing1962(host, satellite, massSatellite, position, velocity, efficiencyCentrifugal=1.0):
    """King (1962) tidal radius: the radius enclosing a mean density

        rho_tidal = (3 / 4 pi) (epsilon omega^2 - T_dominant) / G.

    Returns zero when the tidal field is compressive rather than stretching, matching the code."""
    radius = np.linalg.norm(position)
    frequencyAngular = np.linalg.norm(np.cross(position, velocity)) / radius**2
    tidalFieldRadial = -host.tidalTensorRadial(radius)
    tidalPull = efficiencyCentrifugal * frequencyAngular**2 - tidalFieldRadial
    if tidalPull <= 0.0 or massSatellite <= 0.0:
        return 0.0
    densityTidal = 3.0 / 4.0 / np.pi * tidalPull / gravitationalConstant

    def root(radiusTrial):
        return satellite.massEnclosed(radiusTrial) / (4.0 / 3.0 * np.pi * radiusTrial**3) - densityTidal

    # The mean density falls monotonically outward, so the solution is bracketed between a tiny radius -
    # where the mean density diverges - and the satellite's virial radius.
    radiusLower = 1.0e-6 * satellite.radiusScale
    radiusUpper = satellite.radiusVirial
    if root(radiusLower) <= 0.0:
        return 0.0
    if root(radiusUpper) >= 0.0:
        return radiusUpper
    return brentq(root, radiusLower, radiusUpper, xtol=1.0e-18, rtol=1.0e-14)


def rateMassLossZentner2005(host, satelliteBaryonCorrected, satelliteDarkMatterOnly, massSatellite, position, velocity,
                            timescaleDynamicalHost, efficiency=2.5, useDynamicalTimeScale=True,
                            efficiencyCentrifugal=1.0):
    """Zentner et al. (2005) tidal mass loss rate, in Msun/Gyr.

        dM/dt = - efficiency * M_outside_tidal_radius / timescale

    The timescale is a dynamical time at the tidal radius when `useDynamicalTimeScale` is set, and the
    orbital period otherwise. Frequencies are converted to Gyr^-1 only at the end, since the rate is
    the one quantity here which is per unit time rather than per unit length."""
    radius = np.linalg.norm(position)
    frequencyAngular = np.linalg.norm(np.cross(position, velocity)) / radius**2 * toPerGigaYear
    frequencyRadial = abs(np.dot(position, velocity)) / radius**2 * toPerGigaYear
    frequencyOrbital = max(frequencyAngular, frequencyRadial)
    if frequencyOrbital > 1.0e-6 / timescaleDynamicalHost:
        periodOrbital = 2.0 * np.pi / frequencyOrbital
    else:
        periodOrbital = timescaleDynamicalHost

    # The tidal radius is where the satellite's *physical* mean density falls to the tidal density, so King (1962)
    # uses the baryon-corrected profile; `Zentner2005.F90` then reads the enclosed mass from the dark-matter-only
    # profile, to match the bound mass. That asymmetry is the code's, and is flagged in the module header.
    radiusTidal = radiusTidalKing1962(
        host, satelliteBaryonCorrected, massSatellite, position, velocity, efficiencyCentrifugal
    )
    massEnclosedTidalRadius = (
        max(0.0, satelliteDarkMatterOnly.massEnclosed(radiusTidal)) if radiusTidal > 0.0 else 0.0
    )

    if useDynamicalTimeScale and massEnclosedTidalRadius > 0.0:
        timescaleMassLoss = (
            2.0
            * np.pi
            * np.sqrt(radiusTidal**3 / 16.0 / gravitationalConstant / massEnclosedTidalRadius)
            / toPerGigaYear
        )
    else:
        timescaleMassLoss = periodOrbital

    # Both terms are now total masses: `satelliteDarkMatterOnly` is normalized to the same mass as the bound mass, so
    # a satellite whose tidal radius reaches its virial radius has nothing outside it and loses no mass. Before the
    # fix in `Zentner2005.F90` the enclosed mass came from the baryon-corrected profile, leaving such a satellite
    # with `massOuter` equal to the baryon fraction of its bound mass and so losing mass with nothing stripping it.
    massOuter = max(massSatellite - massEnclosedTidalRadius, 0.0)
    return -efficiency * massOuter / timescaleMassLoss


# The grid of configurations.
#
# What varies is chosen to move the two rates through their distinct regimes, not merely to be numerous.
# The orbital radius sets the host density and dispersion the friction term sees, and the tidal field the
# stripping term sees. The velocity direction separates the two orbital frequencies Zentner et al. (2005)
# takes the larger of - a circular orbit has zero radial frequency and a plunging one has the larger
# radial - and it also moves X = v/(sqrt(2) sigma) across the range where the erf factor is changing.
# The bound mass fraction moves the satellite along its own tidal track, changing which part of its
# profile the tidal radius cuts.
massHaloHost = 1.0e12
concentrationHost = 10.0
logarithmCoulomb = 2.0
efficiencyStripping = 2.5

# A note on what is *not* varied, because the first version of this grid got it wrong. It varied the
# satellite's bound mass while leaving its density profile at the unstripped one. That is not a state
# Galacticus produces - as a satellite is stripped its mass distribution is truncated to match - and it
# made the mass outside the tidal radius, max(M_bound - M(<r_tidal), 0), identically zero. Those rows
# reported a mass loss rate of exactly zero and would have compared zero against zero: five
# configurations that looked like coverage and tested nothing. The satellite's bound mass is therefore
# always the total mass of its profile here, and the structural variation is in the profile itself.
#
# Reproducing a genuinely stripped satellite would mean bringing in the tidal track, which
# `test-tidalTracks.py` already validates against Errani & Navarro (2021); it is deliberately out of
# scope here.
#
# (radius / r_vir, tangential velocity / v_vir, radial velocity / v_vir, satellite mass, satellite concentration)
configurations = [
    (0.20, 1.00,  0.00, 1.0e10, 15.0),
    (0.20, 0.50, -0.50, 1.0e10, 15.0),
    (0.20, 0.20, -0.90, 1.0e10, 15.0),
    (0.50, 1.00,  0.00, 1.0e10, 15.0),
    (0.50, 0.50, -0.50, 1.0e10, 15.0),
    (0.50, 0.20, -0.90, 1.0e10, 15.0),
    (1.00, 1.00,  0.00, 1.0e10, 15.0),
    (1.00, 0.50, -0.50, 1.0e10, 15.0),
    (1.00, 0.20, -0.90, 1.0e10, 15.0),
    (0.50, 0.50, -0.50, 1.0e10,  5.0),
    (0.50, 0.50, -0.50, 1.0e10, 30.0),
    (0.50, 0.50, -0.50, 1.0e09, 15.0),
    (0.50, 0.50, -0.50, 1.0e11, 15.0),
    # Deep inside the satellite's own virial radius, where the Chandrasekhar integral's extended-mass
    # suppression factor min(1, M_sat(<r)/M_sat) is genuinely below one - about 0.37 here - rather than
    # saturated at unity as it is everywhere above. Without a configuration like this that factor is
    # never exercised, and the two rows varying the satellite mass alone would not catch it: at fixed
    # concentration both rates are *exactly* linear in satellite mass, so those rows check the
    # proportionality and nothing else.
    (0.10, 0.50, -0.50, 1.0e11, 15.0),
]


def radiusVirial(mass, densityContrast=200.0, hubbleConstant=67.36):
    """Virial radius for a fixed contrast relative to the mean matter density, matching the companion
    test's parameter file."""
    densityCritical = 3.0 * hubbleConstant**2 / (8.0 * np.pi * gravitationalConstant)
    densityMean = omegaMatter * densityCritical
    return (3.0 * mass / (4.0 * np.pi * densityContrast * densityMean)) ** (1.0 / 3.0)


def grid():
    """Evaluate both rates for every configuration."""
    radiusVirialHost = radiusVirial(massHaloHost)
    velocityVirialHost = np.sqrt(gravitationalConstant * massHaloHost / radiusVirialHost)
    timescaleDynamicalHost = radiusVirialHost / velocityVirialHost * 3.0856775809623245e22 / 1.0e3 / 3.155695200e16
    # Both profiles hold only the dark matter fraction of their halo's mass; see the note on `fractionDarkMatter`.
    host = ProfileNFW(massHaloHost * fractionDarkMatter, radiusVirialHost, concentrationHost)

    results = []
    for fractionRadius, fractionTangential, fractionRadial, massSatellite, concentrationSatellite_ in configurations:
        # The satellite's profile holds the dark fraction of its mass, while the bound mass passed to the rates is
        # the total, as `satelliteMassBoundInitializorBasicMass` sets it.
        # Two normalizations of the same satellite, because the code reaches for different ones in different places;
        # see the note on `fractionDarkMatter`.
        satelliteBaryonCorrected = ProfileNFW(
            massSatellite * fractionDarkMatter, radiusVirial(massSatellite), concentrationSatellite_
        )
        satelliteDarkMatterOnly = ProfileNFW(
            massSatellite                     , radiusVirial(massSatellite), concentrationSatellite_
        )
        position = np.array([fractionRadius * radiusVirialHost, 0.0, 0.0])
        velocity = np.array([fractionRadial * velocityVirialHost, fractionTangential * velocityVirialHost, 0.0])
        acceleration = accelerationDynamicalFriction(
            host, satelliteDarkMatterOnly, massSatellite, position, velocity, logarithmCoulomb
        )
        radiusTidal = radiusTidalKing1962(host, satelliteBaryonCorrected, massSatellite, position, velocity)
        rateMassLoss = rateMassLossZentner2005(
            host, satelliteBaryonCorrected, satelliteDarkMatterOnly, massSatellite, position, velocity,
            timescaleDynamicalHost, efficiency=efficiencyStripping
        )
        results.append(
            {
                "fractionRadius": fractionRadius,
                "fractionTangential": fractionTangential,
                "fractionRadial": fractionRadial,
                "concentrationSatellite": concentrationSatellite_,
                "radius": position[0],
                "velocityRadial": velocity[0],
                "velocityTangential": velocity[1],
                "massSatellite": massSatellite,
                "accelerationX": acceleration[0],
                "accelerationY": acceleration[1],
                "radiusTidal": radiusTidal,
                "rateMassLoss": rateMassLoss,
            }
        )
    return results


def verify(results):
    """Internal checks of the pieces, against limits where a closed form or a sign is known.

    These do not establish that the rates match Galacticus - only that this script is self-consistent.
    A reference which is internally consistent and externally wrong is exactly what the comparison
    against Galacticus is for."""
    radiusVirialHost = radiusVirial(massHaloHost)
    host = ProfileNFW(massHaloHost, radiusVirialHost, concentrationHost)
    failures = 0

    # The friction acceleration must oppose the velocity, component by component.
    for result in results:
        velocity = np.array([result["velocityRadial"], result["velocityTangential"], 0.0])
        acceleration = np.array([result["accelerationX"], result["accelerationY"], 0.0])
        if np.dot(acceleration, velocity) > 0.0:
            print(f"  FAIL: friction does not oppose motion at r/rv={result['fractionRadius']}")
            failures += 1

    # Mass loss must never be positive.
    for result in results:
        if result["rateMassLoss"] > 0.0:
            print(f"  FAIL: positive mass loss rate at r/rv={result['fractionRadius']}")
            failures += 1

    # The enclosed mass of the NFW profile must recover the total at the virial radius.
    massAtVirial = host.massEnclosed(radiusVirialHost)
    if abs(massAtVirial / massHaloHost - 1.0) > 1.0e-12:
        print(f"  FAIL: NFW normalization, M(<r_vir)/M = {massAtVirial / massHaloHost}")
        failures += 1

    # The Jeans dispersion must fall between zero and the virial velocity everywhere sampled, and peak
    # somewhere inside the halo rather than monotonically rising or falling.
    radii = np.logspace(np.log10(0.01 * radiusVirialHost), np.log10(radiusVirialHost), 12)
    dispersions = np.array([host.velocityDispersion(r) for r in radii])
    velocityVirialHost = np.sqrt(gravitationalConstant * massHaloHost / radiusVirialHost)
    if np.any(dispersions <= 0.0) or np.any(dispersions > velocityVirialHost):
        print("  FAIL: velocity dispersion outside (0, v_vir]")
        failures += 1
    if np.argmax(dispersions) in (0, len(dispersions) - 1):
        print("  FAIL: velocity dispersion is monotonic over the sampled range; expected an interior peak")
        failures += 1

    print(f"{'all internal checks passed' if failures == 0 else str(failures) + ' internal check(s) failed'}")
    return failures


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fortran", action="store_true", help="emit the reference values as Fortran array initializers")
    parser.add_argument("--verify", action="store_true", help="run internal self-consistency checks")
    options = parser.parse_args()

    results = grid()
    if options.verify:
        raise SystemExit(1 if verify(results) else 0)
    if options.fortran:
        def emit(name, values, formatString="{:22.15e}"):
            body = ",".join(formatString.format(value).replace("e", "d") for value in values)
            print(f"  {name}=[{body}]")
        print(f"  integer, parameter :: countConfigurations={len(results)}")
        emit("radius", [r["radius"] for r in results])
        emit("velocityRadial", [r["velocityRadial"] for r in results])
        emit("velocityTangential", [r["velocityTangential"] for r in results])
        emit("massSatellite", [r["massSatellite"] for r in results])
        emit("concentrationSatellite", [r["concentrationSatellite"] for r in results])
        emit("accelerationXReference", [r["accelerationX"] for r in results])
        emit("accelerationYReference", [r["accelerationY"] for r in results])
        emit("radiusTidalReference", [r["radiusTidal"] for r in results])
        emit("rateMassLossReference", [r["rateMassLoss"] for r in results])
    else:
        print(f"{'r/rv':>6} {'vt/vv':>6} {'vr/vv':>6} {'M_sat':>9} {'c_sat':>6} {'a_x':>13} {'a_y':>13} {'r_tidal/Mpc':>13} {'dM/dt':>13}")
        for r in results:
            print(
                f"{r['fractionRadius']:6.2f} {r['fractionTangential']:6.2f} {r['fractionRadial']:6.2f} "
                f"{r['massSatellite']:9.2e} {r['concentrationSatellite']:6.1f} "
                f"{r['accelerationX']:13.5e} {r['accelerationY']:13.5e} "
                f"{r['radiusTidal']:13.5e} {r['rateMassLoss']:13.5e}"
            )


if __name__ == "__main__":
    main()
