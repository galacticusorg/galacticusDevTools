#!/usr/bin/env python3
"""Independent reference values for the field away from the mid-plane of a tidally truncated and heated exponential disk.

Galacticus' massDistributionExponentialDiskTidal class describes an exponential disk (unit mass, unit radial scale length,
G = 1, surface density Sigma_e(R) = exp(-R)/(2 pi), and vertical density profile rho_z(z) = sech^2(z/h)/(2 h)) which has been

  * truncated: beyond a truncation radius, R_t, the surface density is multiplied by

        g(u) = u^(1/y_d) exp(-(u-1)/y_d) ,  u = R/R_t ,

    with R_t chosen such that the disk retains a fraction exp(-x) of its mass; and then

  * heated: each ring, at radius R_0, is spread in radius with a log-normal distribution of width
    sigma_lnR = min(s R_0, 1), shifted such that its mean radius is conserved (i.e. ln R' has mean ln R_0 - sigma^2/2).

Galacticus tabulates the field of such disks away from the mid-plane as that of the untruncated, unheated disk, scaled by
ratios of mid-plane quantities, and multiplied by tabulated corrections. This script instead evaluates the field directly. The
Hankel transform of the heated surface density is that of a superposition of rings,

    Sigma~(k) = int_0^inf Sigma(R) J_0(kR) R dR = (1/2 pi) int dM(R_0) < J_0(k R') > ,

where dM(R_0) = 2 pi R_0^2 Sigma_t(R_0) d ln R_0 is the mass of the truncated disk in each ring. For narrow rings the
expectation over the log-normal distribution of R' is evaluated by Gauss-Hermite quadrature. For wide rings, across which
J_0(kR') oscillates too rapidly for that quadrature to converge, the rings are instead summed into a surface density on a fine,
linear grid of R', whose transform is evaluated by Simpson's rule. (Galacticus instead convolves the surface density with the
log-normal distribution on a logarithmic grid of radii, and transforms it using FFTLog.) The field is then

    Phi(R,z) = -2 pi int_0^inf dk     J_0(kR) Sigma~(k) K(k,z) ,
    a_R(R,z) = -2 pi int_0^inf dk   k J_1(kR) Sigma~(k) K(k,z) ,
    a_z(R,z) =  2 pi int_0^inf dk     J_0(kR) Sigma~(k) dK/dz ,

where the vertical kernel, K(k,z) = int dz' rho_z(z') exp(-k|z-z'|), is evaluated by direct quadrature of the convolution,
split at z' = z. The integrals over k use Gauss-Legendre quadrature on panels of width 1/2, up to k = 400 (beyond which the
kernel is below 10^-10 at the heights considered).

These values are used by the "Truncated and heated disk, away from the mid-plane" group of
tests.mass_distributions.exponential_disk_tidal.exe (for x = 1, s = 0.1 and 0.3, h = 0.137 and y_d = 0.1). Run with --heating
0 the script gives the field of the truncated, unheated disk, which Galacticus' own reference (direct numerical integration of
the Hankel transforms, in source/tests/mass_distributions/exponential_disk_tidal/reference.F90) also computes. Run with
--converge it repeats the calculation at twice the resolution in each quadrature, and reports the largest relative change.

Andrew Benson, Claude (6-November-2026).
"""
import argparse
import numpy as np
from scipy.integrate import quad, quad_vec
from scipy.optimize import brentq
from scipy.special import j0, j1, roots_hermite, roots_legendre

# Default evaluation points, in units of the truncation radius and the scale height - those used by the test.
radiiDefault = (0.3, 0.6, 1.0)
heightsDefault = (0.5, 1.0, 2.0, 4.0)


def truncationFactor(R, radiusTruncate, radiusDecayOverRadiusTruncate):
    """Return the factor, g(R/R_t), by which truncation multiplies the surface density."""
    u = np.asarray(R, dtype=float)/radiusTruncate
    return np.where(u > 1.0, np.exp((np.log(np.maximum(u, 1.0)) - (u - 1.0))/radiusDecayOverRadiusTruncate), 1.0)


def radiusTruncate(truncation, radiusDecayOverRadiusTruncate):
    """Return the truncation radius, R_t, at which the truncated disk retains a fraction exp(-x) of its mass."""
    def massRemoved(radiusTruncate_):
        integrand = lambda R: R*np.exp(-R)*(1.0 - truncationFactor(R, radiusTruncate_, radiusDecayOverRadiusTruncate))
        return quad(integrand, radiusTruncate_, radiusTruncate_ + 100.0, epsabs=0.0, epsrel=1.0e-13, limit=500)[0]
    massRetained = np.exp(-truncation)
    return brentq(lambda r: 1.0 - massRemoved(r) - massRetained, 1.0e-3, 1.0e2, xtol=1.0e-14, rtol=1.0e-14)


def transformSurfaceDensity(wavenumber, radiusTruncate_, radiusDecayOverRadiusTruncate, heating, countRing, countHermite, spacingSpread):
    """Return the Hankel transform, Sigma~(k), of the truncated and heated surface density."""
    # Rings, on a grid uniform in ln(R_0), integrated using Simpson's rule.
    lnRadius = np.linspace(np.log(1.0e-5), np.log(radiusTruncate_ + 30.0), countRing)
    radius = np.exp(lnRadius)
    weights = np.full(countRing, 2.0)
    weights[1::2] = 4.0
    weights[0] = weights[-1] = 1.0
    weights *= (lnRadius[1] - lnRadius[0])/3.0
    # Ring masses, multiplied by 2 pi. (A ring of unit mass has Sigma~(k) = J_0(kR)/(2 pi), so the factors of 2 pi cancel.)
    mass = weights*radius**2*np.exp(-radius)*truncationFactor(radius, radiusTruncate_, radiusDecayOverRadiusTruncate)
    width = np.minimum(heating*radius, 1.0)
    # Narrow rings (spread over fewer than 20 spacings of the grid below) are averaged over their log-normal distribution by
    # Gauss-Hermite quadrature. Across such a ring the phase of J_0(kR') changes by no more than about k*20*spacingSpread, so the
    # quadrature converges.
    narrow = width*radius < 20.0*spacingSpread
    nodes, weightsHermite = roots_hermite(countHermite)
    weightsHermite /= np.sqrt(np.pi)
    radiusNarrow = (radius[narrow, None]*np.exp(np.sqrt(2.0)*width[narrow, None]*nodes[None, :] - 0.5*width[narrow, None]**2)).ravel()
    massNarrow = (mass[narrow, None]*weightsHermite[None, :]).ravel()
    # Wide rings are instead summed into a surface density on a fine, linear grid of R', which resolves the oscillations of
    # J_0(kR') at all wavenumbers used (Gauss-Hermite quadrature does not, for the widest rings), and integrated using Simpson's
    # rule. The integrand is Sigma(R') J_0(kR') R' dR' = [sum_i m_i p_i(ln R')/(2 pi)] J_0(kR') dR'/R', where p_i is the
    # log-normal distribution of ring i in ln R'. It vanishes at R'=0, which is therefore omitted.
    countGrid = 2*int(np.ceil(0.5*(radiusTruncate_ + 60.0)/spacingSpread)) + 1
    radiusGrid = np.arange(countGrid)*spacingSpread
    weightsGrid = np.full(countGrid, 2.0)
    weightsGrid[1::2] = 4.0
    weightsGrid[0] = weightsGrid[-1] = 1.0
    weightsGrid *= spacingSpread/3.0
    radiusGrid, weightsGrid = radiusGrid[1:], weightsGrid[1:]
    lnGrid = np.log(radiusGrid)
    densityGrid = np.zeros_like(radiusGrid)
    for radius_, mass_, width_ in zip(radius[~narrow], mass[~narrow], width[~narrow]):
        mean = np.log(radius_) - 0.5*width_**2
        densityGrid += mass_*np.exp(-0.5*((lnGrid - mean)/width_)**2)/np.sqrt(2.0*np.pi)/width_
    radiusAll = np.concatenate((radiusNarrow, radiusGrid))
    massAll = np.concatenate((massNarrow, weightsGrid*densityGrid/radiusGrid))
    # Sum over rings, in chunks of wavenumber to limit memory use.
    transform = np.empty_like(wavenumber)
    for i in range(0, len(wavenumber), 64):
        k = wavenumber[i:i+64]
        transform[i:i+64] = j0(k[:, None]*radiusAll[None, :]) @ massAll
    return transform/(2.0*np.pi)


def kernelVertical(wavenumber, height, scaleHeight):
    """Return the vertical kernel, K(k,z), and its derivative, dK/dz, by direct quadrature of the convolution."""
    density = lambda z: 1.0/np.cosh(z/scaleHeight)**2/(2.0*scaleHeight)
    extent = 40.0*scaleHeight + height
    # Material below (A) and above (B) the height z, as functions of the separation t = |z-z'|.
    below = quad_vec(lambda t: density(height - t)*np.exp(-wavenumber*t), 0.0, extent, epsabs=0.0, epsrel=1.0e-11, norm='max', limit=2000)[0]
    above = quad_vec(lambda t: density(height + t)*np.exp(-wavenumber*t), 0.0, extent, epsabs=0.0, epsrel=1.0e-11, norm='max', limit=2000)[0]
    return below + above, -wavenumber*(below - above)


def field(truncation, heating, scaleHeight, radiusDecayOverRadiusTruncate, radii, heights, resolution=1):
    """Return the truncation radius, the total mass, and the potential, radial, and vertical accelerations at each (R,z)."""
    radiusTruncate_ = radiusTruncate(truncation, radiusDecayOverRadiusTruncate)
    # Gauss-Legendre panels in wavenumber.
    widthPanel = 0.5/resolution
    countPanel = int(round(400.0/widthPanel))
    nodes, weightsLegendre = roots_legendre(8)
    edges = np.arange(countPanel)*widthPanel
    wavenumber = (edges[:, None] + 0.5*widthPanel*(nodes[None, :] + 1.0)).ravel()
    weightsWavenumber = np.tile(0.5*widthPanel*weightsLegendre, countPanel)
    transform = transformSurfaceDensity(wavenumber, radiusTruncate_, radiusDecayOverRadiusTruncate, heating, 5000*resolution + 1, 48*resolution, 1.0e-3/resolution)
    # The total mass, from the transform at k=0.
    mass = 2.0*np.pi*transformSurfaceDensity(np.array([0.0]), radiusTruncate_, radiusDecayOverRadiusTruncate, heating, 5000*resolution + 1, 48*resolution, 1.0e-3/resolution)[0]
    results = []
    for R in radii:
        radius = R*radiusTruncate_
        for z in heights:
            height = z*scaleHeight
            K, dK = kernelVertical(wavenumber, height, scaleHeight)
            potential = -2.0*np.pi*np.sum(weightsWavenumber*j0(wavenumber*radius)*transform*K)
            accelerationRadial = -2.0*np.pi*np.sum(weightsWavenumber*wavenumber*j1(wavenumber*radius)*transform*K)
            accelerationVertical = +2.0*np.pi*np.sum(weightsWavenumber*j0(wavenumber*radius)*transform*dK)
            results.append((R, z, potential, accelerationRadial, accelerationVertical))
    return radiusTruncate_, mass, results


def fortran(values):
    """Format numbers as a Fortran array constructor of double precision literals."""
    return '[' + ','.join(f"{x:.8e}".replace('e', 'd') for x in values) + ']'


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--truncation', type=float, default=1.0, help='the truncation, x, such that the disk retains a fraction exp(-x) of its mass (default: 1)')
    parser.add_argument('--heating', type=float, nargs='+', default=[0.1, 0.3], help='the heating parameter(s), s (default: 0.1 0.3)')
    parser.add_argument('--scaleHeight', type=float, default=0.137, help='disk scale height in units of the radial scale length (default: 0.137)')
    parser.add_argument('--radiusDecayOverRadiusTruncate', type=float, default=0.1, help='the parameter y_d of the truncation (default: 0.1)')
    parser.add_argument('--fortran', action='store_true', help='emit Fortran array constructors, ready to paste into the test')
    parser.add_argument('--converge', action='store_true', help='repeat at twice the resolution, and report the largest relative change')
    arguments = parser.parse_args()
    for heating in arguments.heating:
        radiusTruncate_, mass, results = field(arguments.truncation, heating, arguments.scaleHeight, arguments.radiusDecayOverRadiusTruncate, radiiDefault, heightsDefault)
        if arguments.fortran:
            print(f"! x={arguments.truncation} s={heating} h={arguments.scaleHeight} y_d={arguments.radiusDecayOverRadiusTruncate}: R/R_t={radiiDefault} (outer), z/h={heightsDefault} (inner)")
            for label, column in (('potential', 2), ('accelerationRadial', 3), ('accelerationVertical', 4)):
                print(f"{label}={fortran([r[column] for r in results])}")
        else:
            print(f"x={arguments.truncation} s={heating} h={arguments.scaleHeight} y_d={arguments.radiusDecayOverRadiusTruncate}: R_t={radiusTruncate_:.10f} mass={mass:.10e} (exp(-x)={np.exp(-arguments.truncation):.10e})", flush=True)
            for R, z, potential, accelerationRadial, accelerationVertical in results:
                print(f"  R/R_t={R:3.1f} z/h={z:3.1f}  Phi={potential:.8e}  aR={accelerationRadial:.8e}  az={accelerationVertical:.8e}", flush=True)
        if arguments.converge:
            resultsFine = field(arguments.truncation, heating, arguments.scaleHeight, arguments.radiusDecayOverRadiusTruncate, radiiDefault, heightsDefault, resolution=2)[2]
            change = max(abs(f[c]/r[c] - 1.0) for r, f in zip(results, resultsFine) for c in (2, 3, 4))
            print(f"  largest relative change at twice the resolution: {change:.2e}", flush=True)


if __name__ == '__main__':
    main()
