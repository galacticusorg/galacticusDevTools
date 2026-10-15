#!/usr/bin/env python3
"""Independent reference values for the Galacticus equilibrium galactic structure solver.

This script solves, from the definitions of the physics, for the equilibrium radii of an exponential
disk and a Hernquist spheroid embedded in an NFW dark matter halo which contracts adiabatically in
response to them, following Gnedin et al. (2004):

    halo mass, concentration   ->  virial radius, NFW profile
    disk and spheroid mass, J  ->  specific angular momenta handed to the solver
                               ->  adiabatic contraction of the halo (implicit, Gnedin et al. 2004)
                               ->  total rotation curve
                               ->  coupled equilibrium condition  j = v(r) r  for each component

It is written from the definitions, not by transcribing the Fortran: a port of the code would reproduce
any bug the code contains. In particular the contraction is solved here as a plain two-level root find
(outer: the equilibrium radii; inner: the initial radius at a given final radius), where Galacticus
reaches the same fixed point by fixed-point iteration with oscillation-breaking heuristics. Agreement
between the two is therefore a statement about the solution, not about the algorithm.

What is verified, and what is not
---------------------------------
The equilibrium condition, the contraction relation, and the rotation curves are all reimplemented here
from the papers. The *conventions* below are read from Galacticus and adopted deliberately: they are
definitions of what the solver is being asked to solve, not physics, and a reference which chose
differently would disagree for reasons that are not defects. Each is stated so a reader can check it.

Conventions that must be matched for the comparison to be meaningful
--------------------------------------------------------------------
  * Units. Galacticus' internal system: masses in Msun, lengths in Mpc, velocities in km/s, with
    G = 4.3011827419096073e-9 Mpc (km/s)^2 / Msun.
  * Virial density contrast. The companion unit test pins `virialDensityContrast` to `fixed` at 200
    times the *mean* matter density, so the virial radius is analytic and the comparison does not also
    test the spherical collapse solver, which has its own tests.
  * The specific angular momentum handed to the solver is *not* J/M. The standard disk component passes
    (J/M) x `ratioAngularMomentumSolverRadius` and the standard spheroid component passes
    (J/M) x `ratioAngularMomentumScaleRadius`. Both are 0.5 here, but neither is a flat default and they
    arrive there by different routes, so neither would survive a change of profile unnoticed:
      - the disk's is `radiusStructureSolver` x I_1/I_2 with I_n = int Sigma(R) R^n dR. For an exponential
        disk I_2/I_1 = 2 R_d, and `radiusStructureSolver` is one scale length, giving exactly 1/2.
      - the spheroid's is I_2/I_3 with I_n = int rho(r) r^n dr. For a Hernquist profile I_3 diverges
        logarithmically, so the code takes its documented fallback value of 1/2 instead.
    The Cole et al. (2000) flat-versus-spherical correction to the disk's value defaults to off and is
    left off by the companion test, so it is not applied here.
  * Which radius is solved for. The disk's radius is the exponential scale length; the spheroid's is the
    Hernquist scale radius a.
  * The dark matter term in the rotation curve is spherical, G M_DM(<r)/r, where M_DM is the *contracted*
    profile. The baryonic term is the rotation curve of the baryonic mass distribution, which for the
    disk is its mid-plane rotation curve, not G M(<r)/r. A composite mass distribution adds rotation curves
    in quadrature.
  * The disk is thick: Galacticus' exponential disk has a sech^2 vertical profile with a default scale
    height of 0.137 scale lengths, which the companion test leaves at its default (`--scaleHeight`). Its
    mid-plane rotation curve is computed here as a Hankel transform of the surface density, using the
    closed form of the mid-plane vertical kernel (see `kernelMidplane`) - which Galacticus does not use, as it
    evaluates the kernel numerically at all heights. With `--scaleHeight 0` the razor-thin (Freeman 1970)
    curve is used instead.
  * Gnedin et al. (2004) contraction. The orbit-averaged radius is rbar(r) = A r_vir (r/r_vir)^omega
    with A = 0.8, omega = 0.77 (Galacticus' defaults, with `radiusFractionalPivot` = 1). The initial
    radius r_i at final radius r_f solves

        M_NFW(rbar(r_i)) [ f_i r_i - f_chi r_f ]  =  v_bar^2(rbar(r_f)) rbar(r_f) r_f / G,

    and the contracted dark matter mass is M_DM(<r_f) = f_DM M_NFW(<rbar(r_i(r_f))) evaluated at the
    solved r_i. Note that the baryonic term uses the *rotation curve* at rbar(r_f) rather than the
    spherically enclosed baryonic mass; for a flattened disk these differ, and Galacticus' choice is the
    former. For r_f >= r_vir the halo is taken to be uncontracted, r_i = r_f.
  * The three mass fractions, for an isolated halo with no satellites: f_DM = f_chi = 1 - Omega_b/Omega_M
    and f_i = f_DM + M_baryonic/M_halo.

Output
------
With no arguments the script prints the reference table. With `--fortran` it prints the same numbers as
Fortran array initializers ready to paste into `source/tests/galactic_structure_equilibrium.F90`, and
with `--tolerance` it reports the sensitivity of each solution to the tabulation of the disk rotation
curve that Galacticus interpolates.

Andrew Benson, Claude (16-September-2026; thick disk added 15-October-2026).
"""

import argparse
import sys
from multiprocessing import Pool
import numpy as np
from scipy.integrate import quad
from scipy.interpolate import CubicSpline
from scipy.optimize import brentq
from scipy.special import digamma, i0e, i1e, j1, jn_zeros, k0e, k1e, roots_laguerre

# Newton's constant in Galacticus' internal unit system: Msun, Mpc, km/s.
gravitationalConstant = 4.3011827419096073e-9

# Gnedin et al. (2004) contraction parameters: Galacticus' defaults.
contractionA = 0.80
contractionOmega = 0.77

# Cosmology: Planck 2018, matching the companion test's parameter file.
hubbleConstant = 67.36
omegaMatter = 0.3153
omegaBaryon = 0.0493

# Virial density contrast, relative to the mean matter density.
densityContrast = 200.0


def criticalDensity():
    """Present-day critical density, Msun/Mpc^3."""
    return 3.0 * hubbleConstant**2 / (8.0 * np.pi * gravitationalConstant)


def radiusVirial(massHalo):
    """Virial radius, Mpc, from M = (4/3) pi r^3 Delta rhoMean."""
    densityMean = omegaMatter * criticalDensity()
    return (3.0 * massHalo / (4.0 * np.pi * densityContrast * densityMean)) ** (1.0 / 3.0)


def massNFW(radius, massHalo, radiusVirialHalo, concentration):
    """Mass enclosed within a sphere of the given radius for an NFW profile normalized to massHalo at
    the virial radius."""
    radiusScale = radiusVirialHalo / concentration
    def mu(x):
        return np.log(1.0 + x) - x / (1.0 + x)
    return massHalo * mu(radius / radiusScale) / mu(concentration)


def rotationCurveHernquist(radius, mass, radiusScale):
    """Circular velocity of a Hernquist profile: v^2 = G M r / (r+a)^2."""
    if radius <= 0.0 or mass <= 0.0:
        return 0.0
    return np.sqrt(gravitationalConstant * mass * radius) / (radius + radiusScale)


def massHernquist(radius, mass, radiusScale):
    """Mass enclosed within a sphere of the given radius for a Hernquist profile."""
    if radius <= 0.0 or mass <= 0.0:
        return 0.0
    return mass * radius**2 / (radius + radiusScale) ** 2


def besselFactorExact(halfRadius):
    """The factor y^2 [I0(y) K0(y) - I1(y) K1(y)] appearing in the mid-plane rotation curve of a
    razor-thin exponential disk (Freeman 1970), with y = R / 2 R_d.

    Evaluated with the exponentially scaled Bessel functions, since I(y) and K(y) individually overflow
    and underflow at large y while their products do not."""
    if halfRadius <= 0.0:
        return 0.0
    return halfRadius**2 * (i0e(halfRadius) * k0e(halfRadius) - i1e(halfRadius) * k1e(halfRadius))


# Which evaluation of the Bessel factor the rotation curve uses. This is the exact function everywhere
# except under `--tolerance`, which substitutes Galacticus' tabulated-and-interpolated version in order to
# measure how much that tabulation moves the solution. `besselFactorExact` itself is never rebound, so
# the tabulated version can fall back to it outside the tabulated range.
besselFactorActive = besselFactorExact


# The vertical scale height of the disk, in units of its radial scale length. Galacticus' exponential disk
# has a sech^2 vertical profile with a default scale height of 0.137 scale lengths, which the companion test
# leaves at its default. A scale height of zero selects the razor-thin disk.
scaleHeight = 0.137

# Gauss-Laguerre nodes and weights, used to evaluate the mid-plane vertical kernel at large wavenumber.
laguerreNodes, laguerreWeights = roots_laguerre(80)

# Zeros of J_1, which delimit the intervals over which the Hankel transform is integrated.
besselJ1Zeros = jn_zeros(1, 20000)


def kernelMidplane(wavenumber, height):
    """The vertical kernel in the mid-plane of a disk with a sech^2 vertical profile of scale height h,

        K(k,0) = int dz rho_z(z) exp(-k|z|) = int_0^inf du sech^2(u) exp(-a u),  a = k h,

    with rho_z(z) = sech^2(z/h)/(2h). This has the closed form K = 1 - a beta(1 + a/2), where
    beta(x) = [psi((x+1)/2) - psi(x/2)]/2 and psi is the digamma function. That form loses precision to
    cancellation at large a, where K -> 1/a, so there the integral is instead evaluated by Gauss-Laguerre
    quadrature after substituting t = a u."""
    a = wavenumber * height
    if a < 50.0:
        return 1.0 - a * 0.5 * (digamma((a / 2.0 + 2.0) / 2.0) - digamma((a / 2.0 + 1.0) / 2.0))
    return np.sum(laguerreWeights / np.cosh(laguerreNodes / a) ** 2) / a


def rotationCurveSquaredThickDisk(radius):
    """Mid-plane V_c^2 of a thick exponential disk of unit mass and unit scale length (G = 1), as the Hankel
    transform

        V_c^2(R) = R int_0^inf dk k J_1(kR) K(k,0) / (1+k^2)^(3/2),

    integrated interval by interval between the zeros of J_1."""
    integrand = lambda k: k * j1(k * radius) * kernelMidplane(k, scaleHeight) / (1.0 + k * k) ** 1.5
    total = 0.0
    low = 0.0
    for i, zero in enumerate(besselJ1Zeros):
        high = zero / radius
        delta = quad(integrand, low, high, epsabs=0.0, epsrel=1.0e-11, limit=200)[0]
        total += delta
        low = high
        if i > 10 and abs(delta) < 1.0e-12 * abs(total):
            break
    return radius * total


# The thick-disk rotation curve is tabulated densely (200 points per decade) and interpolated with a cubic
# spline in ln V_c^2 vs ln R. Beyond the table the disk is treated as a point mass (as in Galacticus, and
# accurate to ~exp(-30)); below it V_c^2 is proportional to R^2.
thickDiskRadiusMinimum = 1.0e-4
thickDiskRadiusMaximum = 30.0
thickDiskPointsPerDecade = 200


def thickDiskTabulation(pointsPerDecade, radiusMinimum=thickDiskRadiusMinimum, radiusMaximum=thickDiskRadiusMaximum):
    """Tabulate the thick-disk rotation curve, returning (ln R, ln V_c^2, spline)."""
    count = int(np.log10(radiusMaximum / radiusMinimum) * pointsPerDecade) + 1
    radii = np.geomspace(radiusMinimum, radiusMaximum, count)
    with Pool() as pool:
        rotationCurveSquared = np.array(pool.map(rotationCurveSquaredThickDisk, radii))
    return np.log(radii), np.log(rotationCurveSquared), CubicSpline(np.log(radii), np.log(rotationCurveSquared), bc_type="natural")


thickDiskTable = None


def rotationCurveSquaredThickDiskInterpolated(radius, table=None):
    """Mid-plane V_c^2 of a dimensionless thick disk, interpolated in a tabulation."""
    lnRadii, lnRotationCurveSquared, spline = table if table is not None else thickDiskTable
    if radius > np.exp(lnRadii[-1]):
        return 1.0 / radius
    if radius < np.exp(lnRadii[0]):
        return np.exp(lnRotationCurveSquared[0]) * (radius / np.exp(lnRadii[0])) ** 2
    return np.exp(spline(np.log(radius)))


# Which evaluation of the thick-disk rotation curve is used. As for the Bessel factor, `--tolerance` rebinds
# this to Galacticus' own (coarser) tabulation.
rotationCurveSquaredThickDiskActive = rotationCurveSquaredThickDiskInterpolated


def rotationCurveExponentialDisk(radius, mass, radiusScale):
    """Mid-plane circular velocity of an exponential disk - razor-thin if the scale height is zero."""
    if radius <= 0.0 or mass <= 0.0 or radiusScale <= 0.0:
        return 0.0
    if scaleHeight > 0.0:
        return np.sqrt(gravitationalConstant * (mass / radiusScale) * rotationCurveSquaredThickDiskActive(radius / radiusScale))
    return np.sqrt(
        2.0 * gravitationalConstant * (mass / radiusScale) * besselFactorActive(0.5 * radius / radiusScale)
    )


def rotationCurveBaryonic(radius, massDisk, radiusDisk, massSpheroid, radiusSpheroid):
    """Rotation curve of the combined baryonic mass distribution: components add in quadrature."""
    return np.sqrt(
        rotationCurveExponentialDisk(radius, massDisk, radiusDisk) ** 2
        + rotationCurveHernquist(radius, massSpheroid, radiusSpheroid) ** 2
    )


def radiusOrbitalMean(radius, radiusVirialHalo):
    """Gnedin et al. (2004) orbit-averaged radius, rbar(r) = A r_vir (r/r_vir)^omega."""
    return contractionA * radiusVirialHalo * (radius / radiusVirialHalo) ** contractionOmega


def radiusInitial(radiusFinal, halo, baryons):
    """Solve the Gnedin et al. (2004) relation for the initial radius corresponding to a given final
    radius.

    The relation states that the quantity M(rbar) r is conserved for the orbit-averaged radius, which
    after separating the mass which is and is not distributed like the dark matter becomes the root
    equation documented in the module header."""
    massHalo, radiusVirialHalo, concentration, fractionDarkMatter, fractionInitial = halo
    if radiusFinal >= radiusVirialHalo:
        return radiusFinal
    radiusFinalMean = radiusOrbitalMean(radiusFinal, radiusVirialHalo)
    velocityBaryonic = rotationCurveBaryonic(radiusFinalMean, *baryons)
    termBaryonic = velocityBaryonic**2 * radiusFinalMean * radiusFinal / gravitationalConstant

    def root(radiusTrial):
        massDarkMatterInitial = massNFW(
            radiusOrbitalMean(radiusTrial, radiusVirialHalo), massHalo, radiusVirialHalo, concentration
        )
        return massDarkMatterInitial * (fractionInitial * radiusTrial - fractionDarkMatter * radiusFinal) - termBaryonic

    # The halo contracts, so the initial radius is never smaller than the final one; the virial radius
    # bounds it from above, since beyond it the halo is taken to be unmodified.
    if root(radiusVirialHalo) < 0.0:
        return radiusVirialHalo
    return brentq(root, radiusFinal, radiusVirialHalo, xtol=1.0e-16, rtol=1.0e-14)


def massDarkMatterContracted(radiusFinal, halo, baryons):
    """Mass of the contracted dark matter halo enclosed within a sphere of the given final radius."""
    massHalo, radiusVirialHalo, concentration, fractionDarkMatter, _ = halo
    return fractionDarkMatter * massNFW(
        radiusInitial(radiusFinal, halo, baryons), massHalo, radiusVirialHalo, concentration
    )


def rotationCurveTotal(radius, halo, baryons):
    """Total circular velocity: the spherical dark matter term plus the baryonic rotation curve, in
    quadrature."""
    velocityDarkMatterSquared = gravitationalConstant * massDarkMatterContracted(radius, halo, baryons) / radius
    return np.sqrt(velocityDarkMatterSquared + rotationCurveBaryonic(radius, *baryons) ** 2)


def solveEquilibrium(massHalo, concentration, massDisk, momentumSpecificDisk, massSpheroid, momentumSpecificSpheroid):
    """Solve the coupled equilibrium condition j = v(r) r for the disk and spheroid radii.

    The two radii are coupled: each component's equilibrium radius depends on the total rotation curve,
    which depends on both radii and on the contraction they jointly drive. The system is solved by
    iterating the pair of one-dimensional root finds to convergence, starting from the radii each
    component would have in the uncontracted halo alone."""
    radiusVirialHalo = radiusVirial(massHalo)
    fractionDarkMatter = 1.0 - omegaBaryon / omegaMatter
    fractionInitial = fractionDarkMatter + (massDisk + massSpheroid) / massHalo
    halo = (massHalo, radiusVirialHalo, concentration, fractionDarkMatter, fractionInitial)

    def radiusForAngularMomentum(momentumSpecific, baryons):
        """Radius at which the total rotation curve gives the required specific angular momentum."""
        def root(radius):
            return rotationCurveTotal(radius, halo, baryons) * radius - momentumSpecific
        return brentq(root, 1.0e-8 * radiusVirialHalo, radiusVirialHalo, xtol=1.0e-16, rtol=1.0e-14)

    # Initial guess: each component alone in the uncontracted halo.
    def rotationCurveUncontracted(radius):
        return np.sqrt(gravitationalConstant * fractionDarkMatter * massNFW(radius, massHalo, radiusVirialHalo, concentration) / radius)

    def radiusUncontracted(momentumSpecific):
        return brentq(
            lambda radius: rotationCurveUncontracted(radius) * radius - momentumSpecific,
            1.0e-8 * radiusVirialHalo,
            radiusVirialHalo,
            xtol=1.0e-16,
            rtol=1.0e-14,
        )

    radiusDisk = radiusUncontracted(momentumSpecificDisk)
    radiusSpheroid = radiusUncontracted(momentumSpecificSpheroid)
    for _ in range(200):
        baryons = (massDisk, radiusDisk, massSpheroid, radiusSpheroid)
        radiusDiskNew = radiusForAngularMomentum(momentumSpecificDisk, baryons)
        baryons = (massDisk, radiusDiskNew, massSpheroid, radiusSpheroid)
        radiusSpheroidNew = radiusForAngularMomentum(momentumSpecificSpheroid, baryons)
        change = max(abs(np.log(radiusDiskNew / radiusDisk)), abs(np.log(radiusSpheroidNew / radiusSpheroid)))
        radiusDisk, radiusSpheroid = radiusDiskNew, radiusSpheroidNew
        if change < 1.0e-13:
            break
    else:
        raise RuntimeError("equilibrium radii failed to converge")
    # Confirm that what was returned actually solves the equilibrium condition. The loop above tests only
    # that successive iterates stopped moving, which a converged *wrong* fixed point would also satisfy.
    baryons = (massDisk, radiusDisk, massSpheroid, radiusSpheroid)
    for name, radius, momentumSpecific in (
        ("disk", radiusDisk, momentumSpecificDisk),
        ("spheroid", radiusSpheroid, momentumSpecificSpheroid),
    ):
        residual = abs(rotationCurveTotal(radius, halo, baryons) * radius / momentumSpecific - 1.0)
        if residual > 1.0e-10:
            raise RuntimeError(f"{name} radius does not satisfy j = v(r) r: residual {residual:.3e}")
    return radiusDisk, radiusSpheroid


# The grid of models.
#
# A note on what varies, because a careless grid here tests one model several times. With the
# concentration and the baryonic mass *fractions* held fixed, and the angular momentum expressed in units
# of the halo's own, the whole problem is scale-free in halo mass: every length scales as M^(1/3) and the
# solved radii carry no independent information. That was true of the first version of this grid, whose
# three halo masses agreed with that scaling to all printed digits.
#
# So the grid varies the two dimensionless quantities that do change the solution - the halo
# concentration, which sets how centrally the dark matter sits, and the baryonic mass fraction, which
# sets how strongly the halo contracts - together with the spin, which sets where the components land.
# Two additional halo masses are included at one fixed set of dimensionless parameters, to confirm the
# dimensional scaling itself rather than to probe new physics.
concentrationGrid = [5.0, 10.0, 20.0]
spinGrid = [0.02, 0.05]
fractionMassDiskGrid = [0.010, 0.050]
massHaloReference = 1.0e12
# The spheroid carries a quarter of the disk's mass and a quarter of its specific angular momentum, so
# that it settles well inside the disk and the two components probe different parts of the rotation curve.
ratioMassSpheroidDisk = 0.25
ratioMomentumSpheroidDisk = 0.25
# Both components pass half of their mean specific angular momentum to the solver.
ratioAngularMomentumSolverRadius = 0.5
# The models added purely to exercise the scaling with halo mass.
massHaloScalingGrid = [1.0e11, 1.0e13]
concentrationScaling = 10.0
spinScaling = 0.02
fractionMassDiskScaling = 0.040


def momentumSpecificHalo(massHalo, spin):
    """The characteristic specific angular momentum of a halo of the given mass and spin parameter,
    j = sqrt(2) lambda V_vir r_vir."""
    radiusVirialHalo = radiusVirial(massHalo)
    velocityVirial = np.sqrt(gravitationalConstant * massHalo / radiusVirialHalo)
    return np.sqrt(2.0) * spin * velocityVirial * radiusVirialHalo


def solveModel(massHalo, concentration, spin, fractionMassDisk):
    """Solve one model and return it as a record."""
    massDisk = fractionMassDisk * massHalo
    massSpheroid = ratioMassSpheroidDisk * massDisk
    momentumSpecificMeanDisk = momentumSpecificHalo(massHalo, spin)
    momentumSpecificMeanSpheroid = ratioMomentumSpheroidDisk * momentumSpecificMeanDisk
    radiusDisk, radiusSpheroid = solveEquilibrium(
        massHalo,
        concentration,
        massDisk,
        ratioAngularMomentumSolverRadius * momentumSpecificMeanDisk,
        massSpheroid,
        ratioAngularMomentumSolverRadius * momentumSpecificMeanSpheroid,
    )
    return {
        "massHalo": massHalo,
        "spin": spin,
        "concentration": concentration,
        "massDisk": massDisk,
        "massSpheroid": massSpheroid,
        "angularMomentumDisk": massDisk * momentumSpecificMeanDisk,
        "angularMomentumSpheroid": massSpheroid * momentumSpecificMeanSpheroid,
        "radiusDisk": radiusDisk,
        "radiusSpheroid": radiusSpheroid,
    }


def grid():
    """The grid of models, with their solved equilibrium radii."""
    results = []
    for concentration in concentrationGrid:
        for spin in spinGrid:
            for fractionMassDisk in fractionMassDiskGrid:
                results.append(solveModel(massHaloReference, concentration, spin, fractionMassDisk))
    for massHalo in massHaloScalingGrid:
        results.append(solveModel(massHalo, concentrationScaling, spinScaling, fractionMassDiskScaling))
    return results


# Galacticus does not evaluate the Bessel factor of the disk rotation curve directly. It tabulates it on
# a lattice logarithmic in the half-radius at 100 points per decade, stored in a `table1DLogarithmicLinear`
# and interpolated linearly in the factor. That interpolation, not the root finds, is the largest known
# difference between the two calculations, so its size is what the companion test's tolerance must allow.
besselTabulationPointsPerDecade = 100
besselTabulationHalfRadiusMinimum = 1.0e-6
besselTabulationHalfRadiusMaximum = 1.0e1


def besselFactorTabulated(halfRadius, tabulation):
    """The Bessel factor as Galacticus obtains it: linear interpolation in a table logarithmic in the
    half-radius."""
    abscissae, ordinates = tabulation
    if halfRadius <= abscissae[0] or halfRadius >= abscissae[-1]:
        return besselFactorExact(halfRadius)
    index = np.searchsorted(abscissae, halfRadius) - 1
    fraction = (halfRadius - abscissae[index]) / (abscissae[index + 1] - abscissae[index])
    return ordinates[index] + fraction * (ordinates[index + 1] - ordinates[index])


def besselTabulation():
    """Build the tabulation Galacticus uses."""
    countDecades = np.log10(besselTabulationHalfRadiusMaximum / besselTabulationHalfRadiusMinimum)
    count = int(round(countDecades * besselTabulationPointsPerDecade)) + 1
    abscissae = np.logspace(
        np.log10(besselTabulationHalfRadiusMinimum), np.log10(besselTabulationHalfRadiusMaximum), count
    )
    ordinates = np.array([besselFactorExact(x) for x in abscissae])
    return abscissae, ordinates


def reportTolerance(results):
    """Re-solve every model with the Bessel factor taken from the tabulation Galacticus interpolates,
    and report how far each equilibrium radius moves. This measures the agreement achievable between the
    two calculations, and so justifies the companion test's tolerance. For a thick disk the rotation curve
    is instead taken from a tabulation matching Galacticus' own: 100 points per decade in radius, from 1e-4
    to 30 scale lengths, interpolated with a cubic spline in ln V_c^2 vs ln R."""
    global besselFactorActive, rotationCurveSquaredThickDiskActive
    if scaleHeight > 0.0:
        tabulationThick = thickDiskTabulation(100)
        print("Sensitivity of the solved radii to the thick-disk rotation curve tabulation Galacticus interpolates:")
    else:
        tabulation = besselTabulation()
        print("Sensitivity of the solved radii to the Bessel-factor tabulation Galacticus interpolates:")
    print(f"{'M_halo':>10} {'c':>6} {'spin':>6} {'d(r_disk)':>12} {'d(r_sph)':>12}")
    shiftMaximum = 0.0
    for result in results:
        if scaleHeight > 0.0:
            rotationCurveSquaredThickDiskActive = lambda radius: rotationCurveSquaredThickDiskInterpolated(radius, tabulationThick)
        else:
            besselFactorActive = lambda halfRadius: besselFactorTabulated(halfRadius, tabulation)
        try:
            radiusDisk, radiusSpheroid = solveEquilibrium(
                result["massHalo"],
                result["concentration"],
                result["massDisk"],
                ratioAngularMomentumSolverRadius * result["angularMomentumDisk"] / result["massDisk"],
                result["massSpheroid"],
                ratioAngularMomentumSolverRadius * result["angularMomentumSpheroid"] / result["massSpheroid"],
            )
        finally:
            besselFactorActive = besselFactorExact
            rotationCurveSquaredThickDiskActive = rotationCurveSquaredThickDiskInterpolated
        shiftDisk = abs(radiusDisk / result["radiusDisk"] - 1.0)
        shiftSpheroid = abs(radiusSpheroid / result["radiusSpheroid"] - 1.0)
        shiftMaximum = max(shiftMaximum, shiftDisk, shiftSpheroid)
        print(
            f"{result['massHalo']:10.3e} {result['concentration']:6.1f} {result['spin']:6.3f} "
            f"{shiftDisk:12.3e} {shiftSpheroid:12.3e}"
        )
    print(f"\nLargest fractional shift: {shiftMaximum:.3e}")


def checkThickDiskTabulation():
    """Confirm that interpolation in the dense thick-disk tabulation reproduces the directly integrated
    rotation curve, at points midway between those tabulated, so that the tabulation may be treated as exact."""
    lnRadii = thickDiskTable[0]
    radiiMid = np.exp(0.5 * (lnRadii[:-1] + lnRadii[1:]))[::20]
    with Pool() as pool:
        exact = np.array(pool.map(rotationCurveSquaredThickDisk, radiiMid))
    interpolated = np.array([rotationCurveSquaredThickDiskInterpolated(radius) for radius in radiiMid])
    print(f"Thick disk (h = {scaleHeight}): largest fractional error in interpolated V_c^2 = {np.max(np.abs(interpolated / exact - 1.0)):.1e}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fortran", action="store_true", help="emit the reference values as Fortran array initializers")
    parser.add_argument("--tolerance", action="store_true", help="report the sensitivity to the rotation curve tabulation")
    parser.add_argument("--scaleHeight", type=float, default=0.137, help="disk scale height in units of its scale length; zero for a razor-thin disk (default: 0.137, Galacticus' default)")
    options = parser.parse_args()

    global scaleHeight, thickDiskTable
    scaleHeight = options.scaleHeight
    if scaleHeight > 0.0:
        thickDiskTable = thickDiskTabulation(thickDiskPointsPerDecade)
        checkThickDiskTabulation()
    results = grid()
    if options.tolerance:
        reportTolerance(results)
        return
    if options.fortran:
        def emit(name, values, formatString="{:22.15e}"):
            body = ",".join(formatString.format(value).replace("e", "d") for value in values)
            print(f"  {name}=[{body}]")
        print(f"  integer, parameter :: countModels={len(results)}")
        emit("massHalo", [r["massHalo"] for r in results])
        emit("concentration", [r["concentration"] for r in results])
        emit("massDisk", [r["massDisk"] for r in results])
        emit("massSpheroid", [r["massSpheroid"] for r in results])
        emit("angularMomentumDisk", [r["angularMomentumDisk"] for r in results])
        emit("angularMomentumSpheroid", [r["angularMomentumSpheroid"] for r in results])
        emit("radiusDiskReference", [r["radiusDisk"] for r in results])
        emit("radiusSpheroidReference", [r["radiusSpheroid"] for r in results])
    else:
        print(f"{'M_halo':>10} {'c':>6} {'spin':>6} {'M_disk':>11} {'M_sph':>11} {'r_disk/Mpc':>14} {'r_sph/Mpc':>14}")
        for r in results:
            print(
                f"{r['massHalo']:10.3e} {r['concentration']:6.1f} {r['spin']:6.3f} {r['massDisk']:11.4e} "
                f"{r['massSpheroid']:11.4e} {r['radiusDisk']:14.7e} {r['radiusSpheroid']:14.7e}"
            )


if __name__ == "__main__":
    main()
