#!/usr/bin/env python3
"""Independent reference for the orbital evolution of a single satellite in a static host potential.

This is the companion to `satelliteOrbitRates.py`. That script verifies the two rates driving satellite
evolution pointwise; this one integrates them, so that the *assembly* of those rates into the orbital
differential equations is checked too. A pointwise comparison cannot catch a rate which is correct but
enters the equations of motion with the wrong sign, the wrong factor, or the wrong units, and a
comparison of the integrated trajectory alone cannot tell such a mistake from a wrong rate - which is
why both exist.

The rate functions themselves are imported from `satelliteOrbitRates.py` rather than restated, so the
two references cannot drift apart. What is new here is only the system being integrated:

    dr/dt = v                                         (converted from km/s to Mpc/Gyr)
    dv/dt = a_host(r) (1 + massRatio) + a_friction
    dM/dt = massLossRate

Conventions that must be matched for the comparison to be meaningful
--------------------------------------------------------------------
  * The host acceleration is that of its mass distribution, -G M_host(<r) r_vec / r^3, taken from the
    *baryon-corrected* profile, and converted to km/s/Gyr.
  * `satelliteOrbits.F90` multiplies that acceleration by `1 + massRatio`, converting the two-body
    problem of satellite and host about their common centre of mass into the equivalent one-body problem
    for the satellite's motion relative to a host held fixed. The ratio is
        massRatio = min(1000, max(0, M_sat_enclosed(<r) / M_host_enclosed(<r)))
    with `M_sat_enclosed = max(0, min(M_sat_profile(<r), boundMass))`. Note that this mixes the
    baryon-corrected satellite profile with the total bound mass through the `min`, in the same way the
    two defects corrected in `Zentner2005.F90` and `Chandrasekhar1943.F90` did. It is reproduced here
    because it is what the code does; whether it should also be corrected is an open question, flagged
    rather than settled.
  * The satellite's density profile does *not* change as it is stripped: the companion model omits
    `satelliteTidalHeating`, so only the bound mass evolves. This keeps the comparison about the orbit.

Andrew Benson, Claude (16-September-2026).
"""

import argparse
import numpy as np
from scipy.integrate import solve_ivp

from satelliteOrbitRates import (
    ProfileNFW,
    accelerationDynamicalFriction,
    fractionDarkMatter,
    gravitationalConstant,
    radiusVirial,
    rateMassLossZentner2005,
    toPerGigaYear,
)

# Limits applied to the mass ratio by `satelliteOrbits.F90`.
massRatioMinimum = 0.0
massRatioMaximum = 1.0e3

# The model, matching `testSuite/parameters/satelliteOrbitEvolution.xml` and its tree.
massHost = 1.0e12
concentrationHost = 10.0
massSatelliteInitial = 1.0e10
concentrationSatellite = 15.0
logarithmCoulomb = 2.0
efficiencyStripping = 2.5
timeInitial = 8.0
timeFinal = 13.8
timesOutput = [9.0, 10.0, 11.0, 12.0, 13.0, 13.8]


def accelerationHost(host, position):
    """Gravitational acceleration of the host at the satellite's position, in km/s/Gyr."""
    radius = np.linalg.norm(position)
    if radius <= 0.0:
        return np.zeros(3)
    return (
        -gravitationalConstant
        * host.massEnclosed(radius)
        * np.asarray(position)
        / radius**3
        * toPerGigaYear
    )


def massRatioTwoBody(host, satelliteBaryonCorrected, massBound, position):
    """The factor converting the two-body problem to the equivalent one-body problem."""
    radius = np.linalg.norm(position)
    massEnclosedHost = host.massEnclosed(radius)
    if massEnclosedHost <= 0.0:
        return 0.0
    massEnclosedSatellite = max(0.0, min(satelliteBaryonCorrected.massEnclosed(radius), massBound))
    return min(massRatioMaximum, max(massRatioMinimum, massEnclosedSatellite / massEnclosedHost))


def integrate(rtol=1.0e-11, atol=1.0e-14):
    """Integrate the satellite's orbit and bound mass, returning the trajectory at the output times."""
    radiusVirialHost = radiusVirial(massHost)
    velocityVirialHost = np.sqrt(gravitationalConstant * massHost / radiusVirialHost)
    timescaleDynamicalHost = radiusVirialHost / velocityVirialHost / toPerGigaYear

    host = ProfileNFW(massHost * fractionDarkMatter, radiusVirialHost, concentrationHost)
    radiusVirialSatellite = radiusVirial(massSatelliteInitial)
    satelliteBaryonCorrected = ProfileNFW(
        massSatelliteInitial * fractionDarkMatter, radiusVirialSatellite, concentrationSatellite
    )
    satelliteDarkMatterOnly = ProfileNFW(
        massSatelliteInitial                     , radiusVirialSatellite, concentrationSatellite
    )

    def derivatives(time, state):
        position = state[0:3]
        velocity = state[3:6]
        massBound = state[6]
        if massBound <= 0.0:
            return np.zeros(7)
        acceleration = accelerationHost(host, position) * (
            1.0 + massRatioTwoBody(host, satelliteBaryonCorrected, massBound, position)
        ) + accelerationDynamicalFriction(
            host, satelliteDarkMatterOnly, massBound, position, velocity, logarithmCoulomb
        )
        rateMass = rateMassLossZentner2005(
            host,
            satelliteBaryonCorrected,
            satelliteDarkMatterOnly,
            massBound,
            position,
            velocity,
            timescaleDynamicalHost,
            efficiency=efficiencyStripping,
        )
        return np.concatenate([velocity * toPerGigaYear, acceleration, [rateMass]])

    # The satellite starts at the host's virial radius, falling inward with equal radial and tangential
    # speeds of half the host's virial velocity - the initial conditions stated in the companion tree.
    stateInitial = np.array(
        [
            radiusVirialHost, 0.0, 0.0,
            -0.5 * velocityVirialHost, 0.5 * velocityVirialHost, 0.0,
            massSatelliteInitial,
        ]
    )
    solution = solve_ivp(
        derivatives,
        (timeInitial, timeFinal),
        stateInitial,
        t_eval=timesOutput,
        rtol=rtol,
        atol=atol,
        method="DOP853",
        dense_output=True,
    )
    if not solution.success:
        raise RuntimeError(f"orbit integration failed: {solution.message}")
    radii = np.linalg.norm(solution.y[0:3, :], axis=0)
    return solution.t, radii, solution.y[6, :], solution


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fortran", action="store_true", help="emit the reference values as Python/Fortran literals")
    parser.add_argument("--converge", action="store_true", help="report sensitivity to the integrator tolerance")
    options = parser.parse_args()

    times, radii, masses, _ = integrate()
    if options.converge:
        # Re-integrate with a far looser tolerance. The difference bounds the error of the reference
        # itself, and so sets the floor below which the comparison cannot be pushed.
        _, radiiLoose, massesLoose, _ = integrate(rtol=1.0e-8, atol=1.0e-11)
        print("Sensitivity of the reference trajectory to the integrator tolerance:")
        print(f"{'t/Gyr':>7} {'d(radius)':>12} {'d(mass)':>12}")
        for t, r, rl, m, ml in zip(times, radii, radiiLoose, masses, massesLoose):
            print(f"{t:7.2f} {abs(rl / r - 1.0):12.3e} {abs(ml / m - 1.0):12.3e}")
        return
    if options.fortran:
        def emit(name, values):
            body = ",".join(f"{v:22.15e}" for v in values)
            print(f"{name} = [{body}]")
        emit("timesReference", times)
        emit("radiusReference", radii)
        emit("massBoundReference", masses)
    else:
        print(f"{'t/Gyr':>7} {'radius/Mpc':>14} {'boundMass/Msun':>16} {'M/M0':>8}")
        for t, r, m in zip(times, radii, masses):
            print(f"{t:7.2f} {r:14.7e} {m:16.9e} {m / massSatelliteInitial:8.4f}")


if __name__ == "__main__":
    main()
