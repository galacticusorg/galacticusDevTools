#!/usr/bin/env python3
"""Independent reference values for the Gnedin, Hernquist & Ostriker (1999) satellite tidal heating rate in Galacticus.

Galacticus heats an orbiting satellite through the rate at which its normalized specific heat input
Q grows, where a mass element at radius r gains specific energy Q r^2:

    dQ/dt = (epsilon / 3) [1 + (omega tau)^2]^(-gamma) g_ij G_ij

with g_ij the host's tidal tensor at the satellite's position, G_ij the time integral of that tensor
along the orbit (an evolved property of the satellite), tau the shock duration and omega the orbital
frequency inside the satellite. This script evaluates that rate pointwise over a grid of
configurations, for comparison with `satelliteTidalHeatingRateGnedin1999`.

It is written from the definitions, not by transcribing the Fortran.

Where the formula comes from
----------------------------
In the impulse approximation a tidal shock changes the velocity of a mass element at position x by
dv_i = G_ij x_j. Its energy changes, to first order in the (vanishing on average) cross term, by
dE = |dv|^2 / 2 = x_j x_k G_ij G_ik / 2, and averaging over a sphere, <x_j x_k> = r^2 delta_jk / 3,
gives <dE> = r^2 G_ij G_ij / 6. Differentiating with respect to time, dG_ij/dt = g_ij, gives
d<dE>/dt = r^2 g_ij G_ij / 3 - the factor 1/3 in the rate. Gnedin & Ostriker (1999) found that the
impulsive result is suppressed for stars whose orbital frequency omega is fast compared with the shock,
by the adiabatic correction A(x) = (1 + x^2)^(-gamma) with x = omega tau. epsilon is a calibration
parameter scaling the whole.

The sum g_ij G_ij runs over all nine elements: for symmetric tensors each off-diagonal pair contributes
twice. The grid below uses positions off the coordinate axes and path integrals with non-zero
off-diagonal elements, so that both the orientation of the tidal tensor and the double contraction are
exercised; a position along an axis gives a diagonal tidal tensor and would test neither.

Conventions that must be matched for the comparison to be meaningful
--------------------------------------------------------------------
  * Units. Galacticus' internal system: Msun, Mpc, km/s, with G in Mpc (km/s)^2 / Msun. The tidal
    tensor is in (km/s/Mpc)^2. The path integral G_ij is evolved with time in Gyr, so it is in
    (km/s/Mpc)^2 Gyr. Q is in (km/s/Mpc)^2 (so Q r^2 is a specific energy in (km/s)^2), and its rate is
    in (km/s/Mpc)^2 / Gyr: the product g_ij G_ij is converted by (kilo gigaYear / megaParsec)^2.
  * The tidal tensor is -d^2 Phi / dx_i dx_j of the *host's* mass distribution, without the centrifugal
    term, evaluated at the satellite's actual position (the default `standard` tidal field class). For a
    spherical host it is
        g_ij = G [ -M(<r)/r^3 delta_ij + (3 M(<r)/r^5 - 4 pi rho(r)/r^2) x_i x_j ].
    `--verify` checks this against a finite-difference Hessian of the NFW potential.
  * The host profile holds the dark matter fraction of its mass, (1 - Omega_b/Omega_M) M, since the test
    has no baryonic components; this is the same convention as `satelliteOrbitRates.py`.
  * The shock duration is the radial crossing time, tau = r / |v|, converted to Gyr. Only the speed
    enters, not the direction of the velocity.
  * omega is the circular frequency v_c(r_h) / r_h at the satellite's half-mass radius r_h, in Gyr^-1,
    computed from the satellite's *dark matter* distribution only (`componentTypeAll, massTypeDark`),
    which is normalized to (1 - Omega_b/Omega_M) times its basic mass. The half mass is
        M_h = min(f_DM M_bound, M_DM(<r_vir)) / 2,
    so it is the bound mass converted to a dark mass - this class, unlike the two fixed in
    `satelliteOrbitRates.py`, does not mix a total with a dark mass. r_h is where the untruncated profile
    encloses M_h, and v_c(r_h)^2 = G M_h / r_h.
  * If M_h is not above 10^-6 of the basic mass there is no well-defined half-mass radius, and omega
    falls back to the satellite's virial frequency V_vir / R_vir, with V_vir^2 = G M_basic / R_vir.
  * A negative contraction (a path integral anti-aligned with the current tidal field) gives a negative
    rate, which the code clamps to zero. A zero speed also gives zero.

Output
------
With no arguments the script prints the reference table. `--fortran` emits it as Fortran array
initializers. `--verify` reports internal checks of the pieces.

Andrew Benson, Claude (17-September-2026).
"""

import argparse
import numpy as np
from scipy.optimize import brentq

from satelliteOrbitRates import (
    ProfileNFW,
    expansionFactor,
    fractionDarkMatter,
    gravitationalConstant,
    timeNode,
    toPerGigaYear,
)
from satelliteOrbitRates import radiusVirial as radiusVirialAtExpansionFactor


def radiusVirial(mass):
    """Virial radius at the companion test's epoch, t = 13.8 Gyr, where a = 0.99997 under `matterLambda`.

    Both this and Galacticus' own gigaYear (imported through `toPerGigaYear`) matter: before `satelliteOrbitRates.py`
    was corrected to use them, a Julian gigaYear and a = 1 were together the whole of an initial 2e-4 disagreement."""
    return radiusVirialAtExpansionFactor(mass, expansionFactor=expansionFactor(timeNode))


# The heating rate class parameters, stated explicitly in the companion test's parameter file.
epsilon = 3.0
gamma = 2.5

# The host halo, shared by every configuration.
massHaloHost = 1.0e12
concentrationHost = 10.0


def potentialNFW(profile, radius):
    """The NFW potential, Phi(r) = -4 pi G rho_0 r_s^3 ln(1 + r/r_s) / r, in (km/s)^2. Used only to check
    the tidal tensor by finite differences."""
    return (
        -4.0 * np.pi * gravitationalConstant * profile.densityNormalization * profile.radiusScale**3
        * np.log1p(radius / profile.radiusScale) / radius
    )


def tidalTensor(profile, position):
    """The tidal tensor -d^2 Phi / dx_i dx_j of a spherical distribution at a Cartesian position, in (km/s/Mpc)^2."""
    position = np.asarray(position, dtype=float)
    radius = np.linalg.norm(position)
    massEnclosed = profile.massEnclosed(radius)
    density = profile.density(radius)
    return gravitationalConstant * (
        -massEnclosed / radius**3 * np.identity(3)
        + (3.0 * massEnclosed / radius**5 - 4.0 * np.pi * density / radius**2) * np.outer(position, position)
    )


def tensorCentrifugal(position, velocity):
    """The centrifugal contribution to the tidal tensor, in (km/s/Mpc)^2.

    In the frame co-rotating with the satellite the centrifugal acceleration is -w x (w x r), with angular velocity
    w = r x v / r^2, so its contribution to the tidal tensor dа_i/dx_j is |w|^2 delta_ij - w_i w_j. It is built from the
    angular velocity, not from the velocity: the two coincide only for a circular orbit, and `--verify` checks this against a
    numerical Jacobian of the acceleration."""
    position = np.asarray(position, dtype=float)
    velocity = np.asarray(velocity, dtype=float)
    velocityAngular = np.cross(position, velocity) / np.dot(position, position)
    return np.dot(velocityAngular, velocityAngular) * np.identity(3) - np.outer(velocityAngular, velocityAngular)


def tensorCentrifugalFiniteDifference(position, velocity, step):
    """The centrifugal contribution from a numerical Jacobian of the centrifugal acceleration, for `--verify`."""
    position = np.asarray(position, dtype=float)
    velocityAngular = np.cross(position, velocity) / np.dot(position, position)
    acceleration = lambda x: -np.cross(velocityAngular, np.cross(velocityAngular, x))
    jacobian = np.zeros((3, 3))
    for j in range(3):
        offset = np.zeros(3)
        offset[j] = step
        jacobian[:, j] = (acceleration(position + offset) - acceleration(position - offset)) / (2.0 * step)
    return jacobian


def tidalTensorFiniteDifference(profile, position, step):
    """The tidal tensor from a central finite-difference Hessian of the potential, for `--verify`."""
    position = np.asarray(position, dtype=float)
    hessian = np.zeros((3, 3))
    for i in range(3):
        for j in range(3):
            def phi(di, dj):
                offset = np.zeros(3)
                offset[i] += di * step
                offset[j] += dj * step
                return potentialNFW(profile, np.linalg.norm(position + offset))
            hessian[i, j] = (phi(+1, +1) - phi(+1, -1) - phi(-1, +1) + phi(-1, -1)) / (4.0 * step**2)
    return -hessian


def frequencyOrbitalSatellite(massBasic, massBound, concentration, massSpheroid=0.0, radiusSpheroid=0.0):
    """The satellite's internal orbital frequency, in Gyr^-1, and which branch was used.

    The half-mass radius is that of the satellite's *dark matter*, but the circular velocity there is that of its *total*
    mass distribution, so a baryonic component raises the frequency. The optional spheroid is a Hernquist profile, whose
    enclosed mass is M r^2 / (r + a)^2."""
    radiusVirialSatellite = radiusVirial(massBasic)
    # The dark matter distribution of the satellite, normalized to its dark fraction.
    satelliteDark = ProfileNFW(massBasic * fractionDarkMatter, radiusVirialSatellite, concentration)
    massHalf = 0.5 * min(fractionDarkMatter * massBound, satelliteDark.massEnclosed(radiusVirialSatellite))
    if massHalf > 1.0e-6 * massBasic:
        # The enclosed mass rises monotonically without bound, so the root is bracketed by a tiny radius and a
        # radius well beyond the virial radius.
        radiusHalf = brentq(
            lambda radius: satelliteDark.massEnclosed(radius) - massHalf,
            1.0e-12 * radiusVirialSatellite,
            1.0e+3 * radiusVirialSatellite,
            xtol=1.0e-20,
            rtol=1.0e-14,
        )
        massEnclosed = massHalf
        if massSpheroid > 0.0:
            massEnclosed += massSpheroid * radiusHalf**2 / (radiusHalf + radiusSpheroid) ** 2
        velocityCircular = np.sqrt(gravitationalConstant * massEnclosed / radiusHalf)
        return velocityCircular / radiusHalf * toPerGigaYear, "half-mass"
    velocityVirialSatellite = np.sqrt(gravitationalConstant * massBasic / radiusVirialSatellite)
    return velocityVirialSatellite / radiusVirialSatellite * toPerGigaYear, "virial"


def rateHeating(host, position, velocity, tensorPathIntegrated, massBasic, massBound, concentration,
                massSpheroid=0.0, radiusSpheroid=0.0):
    """The normalized tidal heating rate dQ/dt, in (km/s/Mpc)^2 / Gyr, with its ingredients."""
    radius = np.linalg.norm(position)
    speed = np.linalg.norm(velocity)
    frequency, branch = frequencyOrbitalSatellite(massBasic, massBound, concentration, massSpheroid, radiusSpheroid)
    tensor = tidalTensor(host, position)
    contraction = np.sum(tensor * tensorPathIntegrated)
    if speed <= 0.0:
        return 0.0, dict(frequency=frequency, branch=branch, timescaleShock=np.inf, correction=0.0, contraction=contraction)
    # Mpc / (km/s) to Gyr.
    timescaleShock = radius / speed / toPerGigaYear
    correction = (1.0 + (frequency * timescaleShock) ** 2) ** (-gamma)
    rate = epsilon / 3.0 * correction * contraction * toPerGigaYear**2
    return max(rate, 0.0), dict(
        frequency=frequency, branch=branch, timescaleShock=timescaleShock, correction=correction, contraction=contraction
    )


# The path-integrated tidal tensors, in units of (V_vir/R_vir)^2 Gyr of the host, as the symmetric elements
# (xx, xy, xz, yy, yz, zz). Every one has non-zero off-diagonal elements, which are what distinguish a correct
# double contraction from one counting each off-diagonal pair once. The overall sign of each is chosen per
# configuration (see `aligned` below), since whether a given tensor is aligned with the tidal field depends on the
# position it is paired with.
tensorsPathIntegrated = {
    "A": (+1.00, +0.40, -0.30, -0.50, +0.20, -0.50),
    "B": (+0.30, -0.80, +0.50, +0.60, +0.70, -0.90),
}

# Unit directions for the satellite's position; all but the first lie off every coordinate axis and plane.
directions = {
    "x": (1.0, 0.0, 0.0),
    "d": (1.0, 1.0, 1.0),
    "e": (0.3, -0.5, 0.8),
}

# The grid of configurations.
#
# The radius sets the tidal field, and together with the speed sets the shock duration tau = r/|v|; the
# satellite's concentration and bound mass set its internal frequency omega. Between them these move
# x = omega tau from well below one - where the correction is negligible - to several, where it suppresses
# the rate by orders of magnitude and its exponent gamma matters. Bound-mass fractions below one exercise the
# `min` in the half mass, and the tiny bound mass the fallback to the virial frequency.
#
# The satellite's basic mass is *not* varied. With a fixed virial density contrast every satellite of a given
# concentration has the same mean density, so omega - which scales as the square root of a mean density - is
# independent of mass, and so is the rate: rows varying the mass alone would repeat a row exactly. (The same
# scale-freedom made the first grid of the galactic structure test degenerate.)
#
# `aligned` chooses the sign of the path integral so that its contraction with the tidal field is positive;
# the one row with it false has a negative contraction, and so a rate which the code clamps to zero.
#
# The last three rows give the satellite a Hernquist stellar spheroid. Its circular velocity adds in quadrature to the dark
# matter's at the (dark matter) half-mass radius, raising omega and so suppressing the rate; without such a row nothing would
# distinguish the total mass distribution from the dark matter one. The spheroid is additional to the halo's mass rather than
# taken out of it - a real model would move mass from one to the other, but here only the frequency is under test.
#
# (radius / R_vir, speed / V_vir, direction, path integral, aligned, M_bound / M_basic, c_sat, M_spheroid, a_spheroid / Mpc)
massSatellite = 1.0e10
configurations = [
    (0.10, 2.00, "d", "A", True , 1.00  , 15.0, 0.0   , 0.000),
    (0.30, 1.50, "d", "A", True , 1.00  , 15.0, 0.0   , 0.000),
    (1.00, 0.50, "d", "A", True , 1.00  , 15.0, 0.0   , 0.000),
    (0.30, 0.60, "e", "B", True , 1.00  , 15.0, 0.0   , 0.000),
    (0.30, 4.00, "e", "B", True , 1.00  , 15.0, 0.0   , 0.000),
    (0.30, 1.50, "x", "A", True , 1.00  , 15.0, 0.0   , 0.000),
    (0.30, 1.50, "e", "A", True , 1.00  ,  5.0, 0.0   , 0.000),
    (0.30, 1.50, "e", "A", True , 1.00  , 30.0, 0.0   , 0.000),
    (0.30, 1.50, "e", "B", True , 0.60  , 15.0, 0.0   , 0.000),
    (0.30, 1.50, "d", "B", True , 0.30  , 15.0, 0.0   , 0.000),
    (0.30, 1.50, "d", "B", True , 0.05  , 15.0, 0.0   , 0.000),
    (0.30, 1.50, "d", "B", True , 1.0e-7, 15.0, 0.0   , 0.000),
    (0.30, 1.50, "d", "A", False, 1.00  , 15.0, 0.0   , 0.000),
    (0.30, 1.50, "d", "A", True , 1.00  , 15.0, 1.0e09, 0.002),
    (0.10, 2.00, "e", "B", True , 1.00  , 15.0, 3.0e09, 0.005),
    (0.30, 1.50, "d", "A", True , 0.30  , 15.0, 1.0e09, 0.002),
]


def grid():
    radiusVirialHost = radiusVirial(massHaloHost)
    velocityVirialHost = np.sqrt(gravitationalConstant * massHaloHost / radiusVirialHost)
    host = ProfileNFW(massHaloHost * fractionDarkMatter, radiusVirialHost, concentrationHost)
    scaleTensor = (velocityVirialHost / radiusVirialHost) ** 2
    results = []
    massBasic = massSatellite
    for (fractionRadius, fractionSpeed, direction, labelTensor, aligned, fractionBound, concentration,
         massSpheroid, radiusSpheroid) in configurations:
        unit = np.asarray(directions[direction]) / np.linalg.norm(directions[direction])
        position = fractionRadius * radiusVirialHost * unit
        # The velocity is perpendicular to nothing in particular; only its magnitude enters the rate.
        velocity = fractionSpeed * velocityVirialHost * np.array([0.0, 1.0, 0.0])
        xx, xy, xz, yy, yz, zz = tensorsPathIntegrated[labelTensor]
        tensorPathIntegrated = scaleTensor * np.array([[xx, xy, xz], [xy, yy, yz], [xz, yz, zz]])
        if (np.sum(tidalTensor(host, position) * tensorPathIntegrated) > 0.0) != aligned:
            tensorPathIntegrated = -tensorPathIntegrated
        massBound = fractionBound * massBasic
        tensorTidal = tidalTensor(host, position)
        tensorRotation = tensorCentrifugal(position, velocity)
        unitRadial = position / np.linalg.norm(position)
        rate, details = rateHeating(
            host, position, velocity, tensorPathIntegrated, massBasic, massBound, concentration, massSpheroid, radiusSpheroid
        )
        results.append(
            dict(
                position=position,
                velocity=velocity,
                tensor=tensorPathIntegrated,
                massBasic=massBasic,
                massBound=massBound,
                concentration=concentration,
                massSpheroid=massSpheroid,
                radiusSpheroid=radiusSpheroid,
                onAxis=direction == "x",
                tidalTensor=tensorTidal,
                tensorCentrifugal=tensorRotation,
                tidalTensorRadial=unitRadial @ tensorTidal @ unitRadial,
                tidalTensorRadialCentrifugal=unitRadial @ (tensorTidal + tensorRotation) @ unitRadial,
                rate=rate,
                **details,
            )
        )
    return results


def verify(results):
    """Internal checks of the pieces. These show only that this script is self-consistent."""
    failures = 0
    radiusVirialHost = radiusVirial(massHaloHost)
    host = ProfileNFW(massHaloHost * fractionDarkMatter, radiusVirialHost, concentrationHost)

    # The analytic tidal tensor must match a finite-difference Hessian of the potential, off-axis.
    for direction in directions.values():
        unit = np.asarray(direction) / np.linalg.norm(direction)
        for fractionRadius in (0.1, 0.3, 1.0):
            position = fractionRadius * radiusVirialHost * unit
            analytic = tidalTensor(host, position)
            numeric = tidalTensorFiniteDifference(host, position, 1.0e-4 * np.linalg.norm(position))
            difference = np.max(np.abs(numeric - analytic)) / np.max(np.abs(analytic))
            if difference > 1.0e-6:
                print(f"  FAIL: tidal tensor vs finite differences at r/rv={fractionRadius}: {difference:.2e}")
                failures += 1

    # The trace of the tidal tensor is -4 pi G rho (Poisson's equation).
    for fractionRadius in (0.1, 0.3, 1.0):
        position = fractionRadius * radiusVirialHost * np.array([1.0, 1.0, 1.0]) / np.sqrt(3.0)
        trace = np.trace(tidalTensor(host, position))
        expected = -4.0 * np.pi * gravitationalConstant * host.density(np.linalg.norm(position))
        if abs(trace / expected - 1.0) > 1.0e-12:
            print(f"  FAIL: trace of the tidal tensor is not -4 pi G rho at r/rv={fractionRadius}")
            failures += 1

    # The half-mass radius must enclose the half mass, and the frequency be the circular one there.
    for result in results:
        if result["branch"] != "half-mass" or result["massSpheroid"] > 0.0:
            continue
        radiusVirialSatellite = radiusVirial(result["massBasic"])
        satelliteDark = ProfileNFW(result["massBasic"] * fractionDarkMatter, radiusVirialSatellite, result["concentration"])
        massHalf = 0.5 * min(fractionDarkMatter * result["massBound"], satelliteDark.massEnclosed(radiusVirialSatellite))
        radiusHalf = (gravitationalConstant * massHalf / (result["frequency"] / toPerGigaYear) ** 2) ** (1.0 / 3.0)
        if abs(satelliteDark.massEnclosed(radiusHalf) / massHalf - 1.0) > 1.0e-10:
            print("  FAIL: half-mass radius does not enclose the half mass")
            failures += 1

    # The centrifugal tensor must match a numerical Jacobian of the centrifugal acceleration, and must differ materially from
    # the velocity-based form |v|^2 delta - v v over r^2, which is what Galacticus used before this was corrected; otherwise
    # the assertions built on it could not tell the two apart.
    for result in results:
        position, velocity = result["position"], result["velocity"]
        analytic = tensorCentrifugal(position, velocity)
        numeric = tensorCentrifugalFiniteDifference(position, velocity, 1.0e-4 * np.linalg.norm(position))
        if np.max(np.abs(numeric - analytic)) / np.max(np.abs(analytic)) > 1.0e-6:
            print("  FAIL: centrifugal tensor does not match a numerical Jacobian")
            failures += 1
        velocityForm = (
            np.dot(velocity, velocity) * np.identity(3) - np.outer(velocity, velocity)
        ) / np.dot(position, position)
        if np.max(np.abs(velocityForm - analytic)) / np.max(np.abs(analytic)) < 0.05:
            print("  FAIL: the velocity-based centrifugal form differs by under 5% here")
            failures += 1

    # The configurations must actually span the regimes they are there for.
    corrections = [result["correction"] for result in results if result["rate"] > 0.0]
    if not (min(corrections) < 1.0e-3 and max(corrections) > 0.3):
        print(f"  FAIL: the adiabatic correction spans only [{min(corrections):.2e}, {max(corrections):.2e}]")
        failures += 1
    if not any(result["branch"] == "virial" for result in results):
        print("  FAIL: no configuration takes the virial frequency fallback")
        failures += 1
    if not any(result["contraction"] < 0.0 for result in results):
        print("  FAIL: no configuration has a negative contraction")
        failures += 1
    # A spheroid must change the frequency by enough that the comparison could not pass if it were ignored.
    for result in results:
        if result["massSpheroid"] <= 0.0:
            continue
        frequencyDark, _ = frequencyOrbitalSatellite(result["massBasic"], result["massBound"], result["concentration"])
        if abs(result["frequency"] / frequencyDark - 1.0) < 0.02:
            print("  FAIL: a spheroid changes the orbital frequency by under 2%")
            failures += 1
    # Every off-axis configuration with a positive rate must have off-diagonal elements contributing materially, or
    # the double contraction is not being tested there. (On an axis the tidal tensor is diagonal, so they cannot.)
    for result in results:
        if result["onAxis"]:
            continue
        diagonal = np.sum(np.diag(tidalTensor(host, result["position"])) * np.diag(result["tensor"]))
        if result["rate"] > 0.0 and abs(result["contraction"] - diagonal) < 0.05 * abs(result["contraction"]):
            print("  FAIL: off-diagonal elements contribute under 5% of a contraction")
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
        for i, axis in enumerate("XYZ"):
            emit(f"position{axis}", [r["position"][i] for r in results])
        emit("speed", [np.linalg.norm(r["velocity"]) for r in results])
        for name, (i, j) in zip(("XX", "XY", "XZ", "YY", "YZ", "ZZ"), ((0, 0), (0, 1), (0, 2), (1, 1), (1, 2), (2, 2))):
            emit(f"tensorPathIntegrated{name}", [r["tensor"][i, j] for r in results])
        emit("massSatellite", [r["massBasic"] for r in results])
        emit("massBound", [r["massBound"] for r in results])
        emit("concentrationSatellite", [r["concentration"] for r in results])
        emit("massSpheroid", [r["massSpheroid"] for r in results])
        emit("radiusSpheroid", [r["radiusSpheroid"] for r in results])
        emit("rateHeatingReference", [r["rate"] for r in results])
        # The host's tidal tensor at the satellite's position, with and without the centrifugal term, for the assertions on
        # the tidal field classes themselves.
        for name, (i, j) in zip(("XX", "XY", "XZ", "YY", "YZ", "ZZ"), ((0, 0), (0, 1), (0, 2), (1, 1), (1, 2), (2, 2))):
            emit(f"tidalTensor{name}Reference", [r["tidalTensor"][i, j] for r in results])
        for name, (i, j) in zip(("XX", "XY", "XZ", "YY", "YZ", "ZZ"), ((0, 0), (0, 1), (0, 2), (1, 1), (1, 2), (2, 2))):
            emit(f"tidalTensorCentrifugal{name}Reference", [(r["tidalTensor"] + r["tensorCentrifugal"])[i, j] for r in results])
        emit("tidalTensorRadialReference", [r["tidalTensorRadial"] for r in results])
        emit("tidalTensorRadialCentrifugalReference", [r["tidalTensorRadialCentrifugal"] for r in results])
    else:
        print(f"{'r/Mpc':>10} {'|v|':>8} {'M_bound':>9} {'c':>5} {'M_sph':>9} {'branch':>9} {'omega/Gyr':>10} {'tau/Gyr':>9} {'A(x)':>10} {'g:G':>11} {'dQ/dt':>12}")
        for r in results:
            print(
                f"{np.linalg.norm(r['position']):10.4e} {np.linalg.norm(r['velocity']):8.2f} {r['massBound']:9.2e} "
                f"{r['concentration']:5.1f} {r['massSpheroid']:9.2e} {r['branch']:>9} {r['frequency']:10.4e} {r['timescaleShock']:9.3e} "
                f"{r['correction']:10.3e} {r['contraction']:11.4e} {r['rate']:12.5e}"
            )


if __name__ == "__main__":
    main()
