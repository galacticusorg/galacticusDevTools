#!/usr/bin/env python3
"""Independent reference for the accumulation of tidal heating along a satellite's orbit.

This is the companion to `satelliteTidalHeatingRate.py`. That script verifies the Gnedin, Hernquist &
Ostriker (1999) heating rate pointwise, with the path-integrated tidal tensor G_ij given; this one
integrates the rate along an orbit, so that the *accumulation* of that path integral, and of the heat
input Q it drives, is checked too. A pointwise comparison cannot catch a rate which is correct but
enters the differential equations with the wrong sign, factor or decay term, and a comparison of the
accumulated heating alone cannot distinguish such a mistake from a wrong rate - which is why both exist.

The orbit itself is that of `satelliteOrbitEvolution.py`, whose functions are imported rather than
restated, as are the rate functions of `satelliteTidalHeatingRate.py`. What is new here is only the two
extra equations:

    dG_ij/dt = g_ij - efficiencyDecay G_ij / T_orb
    dQ/dt    = (epsilon/3) [1 + (omega T_shock)^2]^(-gamma) g_ij G_ij

The decay term is not physics but a device of `nodeOperatorSatelliteTidalHeating`: it makes the integral
of g_ij effectively run over the previous orbit - the previous tidal shock - rather than over the whole
orbital history.

Conventions that must be matched for the comparison to be meaningful
--------------------------------------------------------------------
  * T_orb is 2 pi divided by the *larger* of the angular and radial orbital frequencies, which keeps it
    well behaved for both circular and radial orbits, and falls back to the host's dynamical time when
    that frequency is below 1e-6 of its inverse. This mirrors the tidal mass loss rate's treatment.
  * The tidal tensor is the host's at the satellite's actual position, without the centrifugal term.
  * G_ij is symmetric, so six components are integrated.
  * The satellite's density profile does *not* respond to the heating: the companion model keeps
    `darkMatterProfile` as `darkMatterOnly`, so Q accumulates but nothing consumes it. That is
    deliberate - it leaves the orbit identical to `satelliteOrbitEvolution.py`'s and makes this a test of
    the accumulation rather than of the profile's response, which
    `tests.dark_matter_profiles.heated.exe` covers analytically. The satellite's orbital frequency does
    still change, because its *bound mass* falls as it is stripped.
  * A static universe, so the satellite's virial radius is that at an expansion factor of unity; it is
    passed explicitly to the rate, which otherwise assumes the companion unit test's epoch.

Output
------
With no arguments the script prints the trajectory and the accumulated heating. `--fortran` emits the
reference values as Python literals for the test. `--converge` re-integrates at a looser tolerance and
reports the shift, bounding the reference's own error.

Andrew Benson, Claude (17-September-2026).
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
from satelliteOrbitEvolution import (
    accelerationHost,
    concentrationHost,
    concentrationSatellite,
    efficiencyStripping,
    logarithmCoulomb,
    massHost,
    massRatioTwoBody,
    massSatelliteInitial,
    positionInitial,
    timeFinal,
    timeInitial,
    timesOutput,
    velocityInitial,
)
from satelliteTidalHeatingRate import epsilon, gamma, rateHeating, tidalTensor

# The decay efficiency of the path integral, matching the companion model's `nodeOperatorSatelliteTidalHeating`.
efficiencyDecay = 1.0

# The indices of the six independent components of a symmetric rank-2 tensor, in the order Galacticus stores them.
indicesTensor = ((0, 0), (0, 1), (0, 2), (1, 1), (1, 2), (2, 2))


def tensorFromComponents(components):
    """Rebuild a symmetric 3x3 tensor from its six independent components."""
    tensor = np.zeros((3, 3))
    for value, (i, j) in zip(components, indicesTensor):
        tensor[i, j] = value
        tensor[j, i] = value
    return tensor


def periodOrbital(position, velocity, timescaleDynamicalHost):
    """The orbital period, in Gyr: 2 pi over the larger of the angular and radial orbital frequencies."""
    radius = np.linalg.norm(position)
    frequencyAngular = np.linalg.norm(np.cross(position, velocity)) / radius**2 * toPerGigaYear
    frequencyRadial = abs(np.dot(position, velocity)) / radius**2 * toPerGigaYear
    frequency = max(frequencyAngular, frequencyRadial)
    if frequency > 1.0e-6 / timescaleDynamicalHost:
        return 2.0 * np.pi / frequency
    return timescaleDynamicalHost


def integrate(rtol=1.0e-11, atol=1.0e-14):
    """Integrate the orbit, bound mass, path-integrated tidal tensor and accumulated heating."""
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
        tensorPathIntegrated = tensorFromComponents(state[7:13])
        if massBound <= 0.0:
            return np.zeros(14)
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
        # The path integral of the tidal tensor, with its artificial decay over an orbital period.
        tensorTidal = tidalTensor(host, position)
        rateTensor = tensorTidal - efficiencyDecay * tensorPathIntegrated / periodOrbital(
            position, velocity, timescaleDynamicalHost
        )
        # The heating rate, which reads the path integral as it stands.
        rateHeat, _ = rateHeating(
            host,
            position,
            velocity,
            tensorPathIntegrated,
            massSatelliteInitial,
            massBound,
            concentrationSatellite,
            radiusVirialSatellite=radiusVirialSatellite,
        )
        return np.concatenate(
            [
                velocity * toPerGigaYear,
                acceleration,
                [rateMass],
                [rateTensor[i, j] for i, j in indicesTensor],
                [rateHeat],
            ]
        )

    # The initial conditions of the companion tree, imported rather than recomputed - see the note on them in
    # `satelliteOrbitEvolution.py`. The tree starts with no heating and a zero path integral.
    stateInitial = np.concatenate(
        [positionInitial, velocityInitial, [massSatelliteInitial], np.zeros(6), [0.0]]
    )
    solution = solve_ivp(
        derivatives,
        (timeInitial, timeFinal),
        stateInitial,
        t_eval=timesOutput,
        rtol=rtol,
        atol=atol,
        method="DOP853",
    )
    if not solution.success:
        raise RuntimeError(f"integration failed: {solution.message}")
    radii = np.linalg.norm(solution.y[0:3, :], axis=0)
    return solution.t, radii, solution.y[6, :], solution.y[7:13, :], solution.y[13, :]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fortran", action="store_true", help="emit the reference values as Python literals")
    parser.add_argument("--converge", action="store_true", help="report sensitivity to the integrator tolerance")
    options = parser.parse_args()

    times, radii, masses, tensors, heating = integrate()
    if options.converge:
        # Re-integrate with a far looser tolerance. The difference bounds the error of the reference itself,
        # and so sets the floor below which the comparison cannot be pushed.
        _, radiiLoose, massesLoose, _, heatingLoose = integrate(rtol=1.0e-8, atol=1.0e-11)
        print("Sensitivity of the reference to the integrator tolerance:")
        print(f"{'t/Gyr':>7} {'d(radius)':>12} {'d(mass)':>12} {'d(Q)':>12}")
        for t, r, rl, m, ml, q, ql in zip(times, radii, radiiLoose, masses, massesLoose, heating, heatingLoose):
            print(f"{t:7.2f} {abs(rl / r - 1.0):12.3e} {abs(ml / m - 1.0):12.3e} {abs(ql / q - 1.0):12.3e}")
        return
    if options.fortran:
        def emit(name, values):
            body = ",".join(f"{v:22.15e}" for v in values)
            print(f"{name} = [{body}]")
        emit("timesReference", times)
        emit("radiusReference", radii)
        emit("massBoundReference", masses)
        emit("heatingNormalizedReference", heating)
    else:
        print(f"{'t/Gyr':>7} {'radius/Mpc':>13} {'boundMass':>14} {'G_xx':>13} {'G_xy':>13} {'Q':>13}")
        for index, time in enumerate(times):
            print(
                f"{time:7.2f} {radii[index]:13.6e} {masses[index]:14.7e} "
                f"{tensors[0, index]:13.5e} {tensors[1, index]:13.5e} {heating[index]:13.6e}"
            )


if __name__ == "__main__":
    main()
