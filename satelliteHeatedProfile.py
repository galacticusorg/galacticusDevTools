#!/usr/bin/env python3
"""Independent reference for the response of a dark matter profile to tidal heating in Galacticus.

The third of the tidal heating references. `satelliteTidalHeatingRate.py` verifies the Gnedin, Hernquist
& Ostriker (1999) heating *rate* pointwise; `satelliteTidalHeatingEvolution.py` verifies its
*accumulation* along an orbit; this one verifies what the accumulated heat then does to the satellite's
density profile.

A mass shell initially at radius r_i, given specific energy eps(r_i), expands to r_f, found by requiring
that the energy gained equals the change in the shell's binding energy:

    eps(r_i) + (G M(<r_i) / 2) (1/r_f - 1/r_i) = 0

Assuming no shell crossing, the enclosed mass is carried with the shell, M_heated(<r_f) = M(<r_i), from
which the heated density follows:

    rho_heated(r_f) = rho(r_i) (r_i / r_f)^2 dr_i/dr_f.

The specific energy has two terms, of which only the first is exercised by the existing
`tests.dark_matter_profiles.heated.exe` - it sets every second-order coefficient to zero:

    eps_1 = Q r^2
    eps_2 = sqrt(2) f (1 + chi_rv) sqrt(Q) r sigma_1D(r),   f = a_0 + a_1 s + a_2 s^2,  s = dlnrho/dlnr

where Q is the normalized specific heating accumulated along the orbit, sigma_1D is the *unheated*
profile's one-dimensional velocity dispersion, and chi_rv is the position-velocity correlation.

Note on the second-order coefficient
-------------------------------------
The sqrt(2) above is what `source/mass_distributions/spherical/heating/tidal.F90` computes. The class'
own documentation instead gives eps_2 = (2/3) f sigma_rms (1 + chi_rv) sqrt(eps_1) with
sigma_rms = sqrt(3) sigma_1D, which is a coefficient of 2/sqrt(3) = 1.155 rather than sqrt(2) = 1.414 -
the two differ by sqrt(3/2). This script follows the *code*, so the comparison tests everything else;
which of the two is intended is a question for the author, and `--verify` reports the size of the
discrepancy rather than hiding it. A wrong coefficient here is largely degenerate with f, which is a
free parameter, so it would not show up as a failure of any fit.

Conventions that must be matched for the comparison to be meaningful
--------------------------------------------------------------------
  * sigma_1D is the isotropic Jeans solution for the *unheated* NFW profile, which is what the heating
    class evaluates: it is handed the unheated distribution.
  * The heating is applied to a profile normalized to the satellite's dark matter mass; this is a
    statement about which profile, not about the heating, and the comparison is insensitive to it.
  * Only the regime without shell crossing is sampled. Galacticus returns the unheated radius when no
    root exists, so a configuration in that regime would compare two fall-through values and test
    nothing; `--verify` checks that every configuration here has a genuine root.

Output
------
With no arguments the script prints the mapping and the heated profile. `--fortran` emits the reference
values as Fortran array initializers. `--verify` runs internal checks.

Andrew Benson, Claude (17-September-2026).
"""

import argparse
import numpy as np
from scipy.optimize import brentq

from satelliteOrbitRates import ProfileNFW, fractionDarkMatter, gravitationalConstant, radiusVirial

# The satellite whose profile is heated: the same halo as the orbit references.
massSatellite = 1.0e10
concentrationSatellite = 15.0

# The second-order heating coefficients. These are deliberately non-zero: with them zero - as in
# `tests.dark_matter_profiles.heated.exe` - the entire second-order term, and the velocity dispersion and
# density slope it is built from, drop out of the calculation.
coefficientSecondOrder0 = 0.05
coefficientSecondOrder1 = 0.01
coefficientSecondOrder2 = 0.005
correlationVelocityRadius = -0.3


def densityLogSlope(profile, radius):
    """dln rho/dln r for an NFW profile: -(1 + 2 x/(1+x)) with x = r/r_s."""
    x = radius / profile.radiusScale
    return -(1.0 + 2.0 * x / (1.0 + x))


def specificEnergy(profile, radius, heatSpecificNormalized, secondOrder=True):
    """The specific energy deposited at `radius`, in (km/s)^2, with its two terms."""
    energyFirstOrder = heatSpecificNormalized * radius**2
    if not secondOrder or heatSpecificNormalized <= 0.0:
        return energyFirstOrder, 0.0
    coefficient = (
        coefficientSecondOrder0
        + coefficientSecondOrder1 * densityLogSlope(profile, radius)
        + coefficientSecondOrder2 * densityLogSlope(profile, radius) ** 2
    )
    energySecondOrder = (
        np.sqrt(2.0)
        * coefficient
        * (1.0 + correlationVelocityRadius)
        * np.sqrt(heatSpecificNormalized)
        * radius
        * profile.velocityDispersion(radius)
    )
    return energyFirstOrder, energySecondOrder


def radiusInitial(profile, radiusFinal, heatSpecificNormalized, secondOrder=True):
    """The initial radius of the shell which heating moves to `radiusFinal`.

    Solves eps(r_i) + (G M(<r_i)/2)(1/r_f - 1/r_i) = 0. The root lies below r_f, since heating can only
    move a shell outward."""

    def root(radiusTrial):
        first, second = specificEnergy(profile, radiusTrial, heatSpecificNormalized, secondOrder)
        return (
            first
            + second
            + 0.5 * gravitationalConstant * profile.massEnclosed(radiusTrial) * (1.0 / radiusFinal - 1.0 / radiusTrial)
        )

    # At r_i -> r_f the binding-energy term vanishes and the root function is positive (the heating term);
    # at small r_i it is dominated by -G M/2 r_i, which is negative. Bracket between the two.
    radiusLower = 1.0e-6 * radiusFinal
    if root(radiusLower) > 0.0:
        return None
    return brentq(root, radiusLower, radiusFinal, xtol=1.0e-24, rtol=1.0e-15)


def heatedProfile(profile, radiusFinal, heatSpecificNormalized, secondOrder=True):
    """The initial radius, enclosed mass and density of the heated profile at `radiusFinal`."""
    initial = radiusInitial(profile, radiusFinal, heatSpecificNormalized, secondOrder)
    if initial is None:
        return None
    massEnclosed = profile.massEnclosed(initial)
    # dr_i/dr_f by central differences on the root itself; the root is solved to machine precision, so a
    # step of 1e-5 in the logarithm leaves the derivative good to ~1e-10.
    step = 1.0e-5
    initialUpper = radiusInitial(profile, radiusFinal * (1.0 + step), heatSpecificNormalized, secondOrder)
    initialLower = radiusInitial(profile, radiusFinal * (1.0 - step), heatSpecificNormalized, secondOrder)
    derivative = (initialUpper - initialLower) / (2.0 * step * radiusFinal)
    density = profile.density(initial) * (initial / radiusFinal) ** 2 * derivative
    return initial, massEnclosed, density


# The configurations: heating strengths in units of the satellite's own (V_vir/r_vir)^2 - the scale the
# `orbiting` satellite component itself uses for this property - and radii in units of its virial radius.
# The strengths span a factor of ten and the radii span the scale radius, where the density slope entering
# the second-order coefficient passes through -2.
#
# The coefficients above are small because the second-order term scales as sqrt(Q) against the first
# order's Q, so it dominates at weak heating for any coefficient of order unity: with the value 0.5 first
# tried here it reached thirty times the first-order term, which is outside the regime the expansion
# describes. As set, it runs from a few per cent to a few tens of per cent of the first-order term - large
# enough that getting it wrong cannot pass, small enough to remain a perturbation.
heatingsNormalized = [0.50, 1.50, 4.00]
radiiFractional = [0.10, 0.30, 0.60, 1.00]


def grid(secondOrder=True):
    radiusVirialSatellite = radiusVirial(massSatellite)
    velocityVirialSatellite = np.sqrt(gravitationalConstant * massSatellite / radiusVirialSatellite)
    scaleHeating = (velocityVirialSatellite / radiusVirialSatellite) ** 2
    profile = ProfileNFW(massSatellite * fractionDarkMatter, radiusVirialSatellite, concentrationSatellite)
    results = []
    for heatingFractional in heatingsNormalized:
        for radiusFractional in radiiFractional:
            heating = heatingFractional * scaleHeating
            radius = radiusFractional * radiusVirialSatellite
            solution = heatedProfile(profile, radius, heating, secondOrder)
            first, second = specificEnergy(profile, radius, heating, secondOrder)
            results.append(
                dict(
                    heatingFractional=heatingFractional,
                    radiusFractional=radiusFractional,
                    heating=heating,
                    radius=radius,
                    radiusInitial=None if solution is None else solution[0],
                    massEnclosed=None if solution is None else solution[1],
                    density=None if solution is None else solution[2],
                    energyFirstOrder=first,
                    energySecondOrder=second,
                )
            )
    return results


def verify(results):
    failures = 0
    radiusVirialSatellite = radiusVirial(massSatellite)
    profile = ProfileNFW(massSatellite * fractionDarkMatter, radiusVirialSatellite, concentrationSatellite)

    # Every configuration must have a genuine root: heating must move the shell outward by a measurable
    # amount, but not so far that the no-shell-crossing assumption fails and Galacticus falls through to
    # the unheated radius.
    for result in results:
        if result["radiusInitial"] is None:
            print(f"  FAIL: no root at Q/(V/r)^2={result['heatingFractional']}, r/rv={result['radiusFractional']}")
            failures += 1
            continue
        expansion = result["radius"] / result["radiusInitial"]
        if expansion < 1.01:
            print(f"  FAIL: heating moves the shell by under 1% at r/rv={result['radiusFractional']}")
            failures += 1

    # The enclosed mass of the heated profile must be below the unheated one at the same radius - mass has
    # moved outward - and the density likewise.
    for result in results:
        if result["radiusInitial"] is None:
            continue
        if result["massEnclosed"] >= profile.massEnclosed(result["radius"]):
            print("  FAIL: heating did not reduce the enclosed mass")
            failures += 1
        if result["density"] >= profile.density(result["radius"]):
            print("  FAIL: heating did not reduce the density")
            failures += 1

    # The second-order term must matter. It is the term the existing test switches off, so if it were
    # negligible here this reference would add nothing.
    ratios = [abs(r["energySecondOrder"] / r["energyFirstOrder"]) for r in results]
    if max(ratios) < 0.05:
        print(f"  FAIL: the second-order term reaches only {max(ratios):.3f} of the first order")
        failures += 1

    # Report the size of the documentation discrepancy in the second-order coefficient, which this script
    # resolves in favour of the code. This is informational, not a failure.
    print(f"  the second-order term is {min(ratios):.3f} to {max(ratios):.3f} of the first order;")
    print(f"  the class' documentation would make it smaller by a factor sqrt(3/2) = {np.sqrt(1.5):.4f}")

    print(f"{'all internal checks passed' if failures == 0 else str(failures) + ' internal check(s) failed'}")
    return failures


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fortran", action="store_true", help="emit the reference values as Fortran array initializers")
    parser.add_argument("--verify", action="store_true", help="run internal self-consistency checks")
    parser.add_argument("--first-order", action="store_true", help="switch off the second-order heating term")
    options = parser.parse_args()

    results = grid(secondOrder=not options.first_order)
    if options.verify:
        raise SystemExit(1 if verify(results) else 0)
    if options.fortran:
        def emit(name, values, formatString="{:22.15e}"):
            body = ",".join(formatString.format(value).replace("e", "d") for value in values)
            print(f"  {name}=[{body}]")
        print(f"  integer, parameter :: countConfigurations={len(results)}")
        emit("heatingNormalized", [r["heating"] for r in results])
        emit("radius", [r["radius"] for r in results])
        emit("radiusInitialReference", [r["radiusInitial"] for r in results])
        emit("massEnclosedReference", [r["massEnclosed"] for r in results])
        emit("densityReference", [r["density"] for r in results])
    else:
        print(f"{'Q/(V/r)^2':>10} {'r/rv':>6} {'r_i/Mpc':>13} {'M(<r)':>14} {'rho':>13} {'eps2/eps1':>10}")
        for r in results:
            print(
                f"{r['heatingFractional']:10.2f} {r['radiusFractional']:6.2f} {r['radiusInitial']:13.6e} "
                f"{r['massEnclosed']:14.7e} {r['density']:13.6e} "
                f"{r['energySecondOrder'] / r['energyFirstOrder']:10.4f}"
            )


if __name__ == "__main__":
    main()
