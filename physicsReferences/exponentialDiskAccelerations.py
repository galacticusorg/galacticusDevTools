#!/usr/bin/env python3
"""Independent reference values for the accelerations, potential, and rotation curve of a thick exponential disk.

Galacticus' massDistributionExponentialDisk class tabulates the acceleration and tidal tensor of a
disk with surface density Sigma(R) = exp(-R)/(2 pi) (unit mass, unit radial scale length, G = 1) and
vertical density profile

    rho_z(z) = sech^2(z/h) / (2 h) ,

each as a Hankel transform of the surface density multiplied by a vertical kernel, K(k,z), which is
the convolution of rho_z with the razor-thin kernel exp(-k|z|). The Hankel transform of the
exponential surface density is (1+k^2)^(-3/2) / (2 pi), so that

    a_R(R,z) = - int_0^inf dk  k J_1(kR) K(k,z)    (1+k^2)^(-3/2) ,
    a_z(R,z) =   int_0^inf dk    J_0(kR) dK/dz     (1+k^2)^(-3/2) ,
    Phi(R,z) = - int_0^inf dk    J_0(kR) K(k,z)    (1+k^2)^(-3/2) ,

and the mid-plane rotation curve is V_c^2(R) = -R a_R(R,0).

Galacticus evaluates K(k,z) as a Laplace-type integral over the offset from the height z (see
kernelVerticalDirect in source/mass_distributions/cylindrical/exponential_disk.F90). This script
instead evaluates the convolution directly,

    K(k,z)  = int dz' rho_z(z') exp(-k|z-z'|) ,
    dK/dz   = int dz' rho_z(z') (-k) sgn(z-z') exp(-k|z-z'|) ,

breaking the range of z' at 0 and at z, and truncating it at |z'| = 40 h + z, beyond which rho_z is
negligible. It therefore shares none of the algebra used to derive Galacticus' form of the kernel. The
Hankel transforms are evaluated interval by interval between successive zeros of the Bessel function,
stopping once an interval contributes less than 10^-9 of the running total.

These values are used by the "Acceleration matches reference values", "Potential matches reference
values", and "Rotation curve matches reference values" groups of tests.mass_distributions.exe, which
test disks with scale heights of 0.01 (the default here) and 0.137 (run with --scaleHeight 0.137). They
detected an error in the kernel previously used by Galacticus,
which placed half of the disk mass in the sech^2 layer and half in a razor-thin sheet (galacticus
issue #78).

Andrew Benson, Claude (13-October-2026).
"""
import argparse
import numpy as np
from scipy.integrate import quad
from scipy.special import j0, j1, jn_zeros

# Default (R,z) points, and mid-plane radii - those used by tests.mass_distributions.exe.
pointsDefault = ((1.0, 0.01), (1.0, 0.1), (0.5, 0.03), (2.0, 0.3))
radiiDefault = (0.1, 0.5, 1.0, 2.2)
# Points, below the smallest radius and/or height tabulated by Galacticus, at which only the potential is tested.
pointsPotential = ((1.0, 0.0), (0.005, 0.005))


def kernel(k, z, h):
    """Return the vertical kernel, K(k,z), and its z derivative, by direct convolution."""
    rho = lambda zp: 1.0/np.cosh(zp/h)**2/(2.0*h)
    L = 40.0*h+z
    ranges = ((-L, 0.0), (0.0, z), (z, L))
    K = sum(quad(lambda zp: rho(zp)*np.exp(-k*abs(z-zp)), a, b, epsabs=0.0, epsrel=1.0e-10, limit=200)[0] for a, b in ranges)
    dK = sum(quad(lambda zp: -k*np.sign(z-zp)*rho(zp)*np.exp(-k*abs(z-zp)), a, b, epsabs=0.0, epsrel=1.0e-10, limit=200)[0] for a, b in ranges)
    return K, dK


def hankel(integrand, bessel, zeros, R):
    """Integrate integrand(k)*bessel(kR) over k, interval by interval between the zeros of the Bessel function."""
    total = 0.0
    low = 0.0
    for i, zero in enumerate(zeros):
        high = zero/R
        delta = quad(lambda k: integrand(k)*bessel(k*R), low, high, epsabs=0.0, epsrel=1.0e-8, limit=200)[0]
        total += delta
        low = high
        if i > 10 and abs(delta) < 1.0e-9*abs(total):
            break
    return total


def accelerations(R, z, h):
    """Return the radial and vertical accelerations at (R,z) for a disk of scale height h."""
    accelerationRadial = hankel(lambda k: -k*kernel(k, z, h)[0]/(1.0+k*k)**1.5, j1, jn_zeros(1, 4000), R)
    accelerationVertical = hankel(lambda k: kernel(k, z, h)[1]/(1.0+k*k)**1.5, j0, jn_zeros(0, 4000), R)
    return accelerationRadial, accelerationVertical


def potential(R, z, h):
    """Return the potential at (R,z) for a disk of scale height h."""
    return hankel(lambda k: -kernel(k, z, h)[0]/(1.0+k*k)**1.5, j0, jn_zeros(0, 4000), R)


def rotationCurve(R, h):
    """Return the mid-plane rotation curve at radius R for a disk of scale height h."""
    accelerationRadial = hankel(lambda k: -k*kernel(k, 0.0, h)[0]/(1.0+k*k)**1.5, j1, jn_zeros(1, 4000), R)
    return np.sqrt(-R*accelerationRadial)


def fortran(x):
    """Format a number as a Fortran double precision literal."""
    return f"{x:.8e}".replace('e', 'd')


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--scaleHeight', type=float, default=0.01, help='disk scale height in units of the radial scale length (default: 0.01)')
    parser.add_argument('--fortran', action='store_true', help='emit Fortran assignments, ready to paste into the test')
    arguments = parser.parse_args()
    h = arguments.scaleHeight
    for R, z in pointsDefault:
        accelerationRadial, accelerationVertical = accelerations(R, z, h)
        potential_ = potential(R, z, h)
        if arguments.fortran:
            print(f"           radiusCylindrical    ={R}d0")
            print(f"           height               ={z}d0")
            print(f"           accelerationReference=[{fortran(accelerationRadial)},0.0d0,{fortran(accelerationVertical)}]")
            print(f"           potentialReference   ={fortran(potential_)}")
        else:
            print(f"h={h} R={R} z={z}  aR={accelerationRadial:.8e}  az={accelerationVertical:.8e}  Phi={potential_:.8e}", flush=True)
    for R, z in pointsPotential:
        potential_ = potential(R, z, h)
        if arguments.fortran:
            print(f"           radiusCylindrical    ={R}d0")
            print(f"           height               ={z}d0")
            print(f"           potentialReference   ={fortran(potential_)}")
        else:
            print(f"h={h} R={R} z={z}  Phi={potential_:.8e}", flush=True)
    for R in radiiDefault:
        rotationCurve_ = rotationCurve(R, h)
        if arguments.fortran:
            print(f"           radius                 ={R}d0")
            print(f"           rotationCurveReference ={fortran(rotationCurve_)}")
        else:
            print(f"h={h} R={R} z=0  Vc={rotationCurve_:.8e}", flush=True)


if __name__ == '__main__':
    main()
