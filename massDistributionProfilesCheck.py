#!/usr/bin/env python3
"""Independent reference values for the Einasto and Burkert mass distributions.

Both profiles are defined by their density alone; everything else - the enclosed mass, the
potential, the total mass, the half-mass radius, the peak of the rotation curve - follows from it by
integration. Galacticus evaluates all of those from closed forms (incomplete Gamma functions for
Einasto, logarithms and arctangents for Burkert). This script instead integrates the density
numerically, so the closed forms can be checked against something that shares none of their algebra.

Everything is computed scale-free, with r_s = 1 and the density normalization = 1, so that

    M(x)    is in units of rho_0 r_s^3 ,
    Phi(x)  is in units of G rho_0 r_s^2 .

Einasto (e.g. Cardone et al. 2005), with shape parameter alpha and r_{-2} = 1:

    rho(x) = exp( -(2/alpha) [ x^alpha - 1 ] )

Burkert (1995), with r_s = 1:

    rho(x) = 1 / [ (1+x) (1+x^2) ]

The potential is taken with the usual zero point at infinity,

    Phi(x) = -4 pi [ (1/x) int_0^x s^2 rho ds + int_x^inf s rho ds ] ,

which is what both Galacticus implementations use. The outer integral is transformed by s = x/t onto
(0,1] so that the infinite range is handled without truncation - integrating to a large finite radius
instead gives a badly wrong answer for Burkert, whose rho falls only as s^-3.

Usage:  ./massDistributionProfilesCheck.py [--fortran]

  --fortran   emit the values as Fortran array constructors, ready to paste into
              source/tests/mass_distributions/Einasto_Burkert.F90
"""
import argparse
import math

from scipy.integrate import quad
from scipy.optimize  import brentq

# Radii and shape parameters at which references are produced.
alphasEinasto  = [0.12, 0.17, 0.30]
radiiEinasto   = [0.01, 0.10, 1.00, 3.00, 10.00]
# The Burkert radii deliberately reach far below the scale radius: the enclosed mass there is the
# difference of terms which cancel to leading order, so it is where a series expansion is needed and
# where an error in one will show.
radiiBurkert   = [1.0e-6, 1.0e-5, 1.0e-4, 1.0e-3, 1.0e-2, 1.0e-1, 1.0e0, 1.0e1, 1.0e2]

toleranceQuad  = 1.0e-13

def densityEinasto(x, alpha):
    return math.exp(-(2.0/alpha)*(x**alpha-1.0))

def densityBurkert(x):
    return 1.0/((1.0+x)*(1.0+x*x))

def massEnclosed(density, x):
    """4 pi int_0^x s^2 rho(s) ds."""
    return 4.0*math.pi*quad(lambda s: s*s*density(s), 0.0, x,
                            limit=400, epsabs=0.0, epsrel=toleranceQuad)[0]

def potential(density, x):
    """-4 pi [ (1/x) int_0^x s^2 rho ds + int_x^inf s rho ds ], zero point at infinity."""
    inner = quad(lambda s: s*s*density(s), 0.0, x,
                 limit=400, epsabs=0.0, epsrel=toleranceQuad)[0]
    # s = x/t maps [x,inf) onto (0,1]; ds = -x/t^2 dt.
    outer = quad(lambda t: (x/t)*density(x/t)*x/t**2, 0.0, 1.0,
                 limit=400, epsabs=0.0, epsrel=toleranceQuad)[0]
    return -4.0*math.pi*(inner/x+outer)

def massTotalEinasto(alpha):
    return 4.0*math.pi*quad(lambda s: s*s*densityEinasto(s, alpha), 0.0, math.inf,
                            limit=400, epsabs=0.0, epsrel=toleranceQuad)[0]

def radiusHalfMassEinasto(alpha):
    half = 0.5*massTotalEinasto(alpha)
    return brentq(lambda x: massEnclosed(lambda s: densityEinasto(s, alpha), x)-half,
                  1.0e-3, 1.0e3, xtol=1.0e-15, rtol=8.9e-16)

def radiusRotationCurveMaximumBurkert():
    """Peak of M(x)/x, i.e. the root of x M'(x) = M(x) with M'(x) = 4 pi x^2 rho(x).

    Found as a root rather than by minimizing M(x)/x directly: the peak is flat, so a minimizer
    locates it only to about the square root of machine precision.
    """
    def stationary(x):
        return 4.0*math.pi*x**3*densityBurkert(x)-massEnclosed(densityBurkert, x)
    return brentq(stationary, 1.0, 10.0, xtol=1.0e-15, rtol=8.9e-16)

def fortranArray(values):
    """Fortran array constructor of double-precision literals: 1.23456789012345d-02, not ...e-02."""
    return "[" + ",".join(("%.14e" % v).replace("e", "d") for v in values) + "]"

def main():
    parser = argparse.ArgumentParser(description="Reference values for the Einasto and Burkert mass distributions.")
    parser.add_argument("--fortran", action="store_true", help="emit Fortran array constructors")
    arguments = parser.parse_args()

    massesEinasto     = []
    potentialsEinasto = []
    for alpha in alphasEinasto:
        density = lambda s, a=alpha: densityEinasto(s, a)
        massesEinasto    .append([massEnclosed(density, x) for x in radiiEinasto])
        potentialsEinasto.append([potential   (density, x) for x in radiiEinasto])
    massesTotalEinasto  = [massTotalEinasto     (alpha) for alpha in alphasEinasto]
    radiiHalfMassEinasto= [radiusHalfMassEinasto(alpha) for alpha in alphasEinasto]

    massesBurkert     = [massEnclosed(densityBurkert, x) for x in radiiBurkert]
    potentialsBurkert = [potential   (densityBurkert, x) for x in radiiBurkert]
    radiusPeakBurkert = radiusRotationCurveMaximumBurkert()
    velocityPeakBurkert = math.sqrt(massEnclosed(densityBurkert, radiusPeakBurkert)/radiusPeakBurkert)

    if arguments.fortran:
        print("! Einasto, shape parameters "+", ".join("%.2f" % a for a in alphasEinasto))
        print("radii            ="+fortranArray(radiiEinasto))
        for alpha, masses, potentials in zip(alphasEinasto, massesEinasto, potentialsEinasto):
            print("! alpha = %.2f" % alpha)
            print("massReference    ="+fortranArray(masses    ))
            print("potentialReference="+fortranArray(potentials))
        print("massTotalReference     ="+fortranArray(massesTotalEinasto  ))
        print("radiusHalfMassReference="+fortranArray(radiiHalfMassEinasto))
        print("! Burkert")
        print("radiiBurkert     ="+fortranArray(radiiBurkert     ))
        print("massReference    ="+fortranArray(massesBurkert    ))
        print("potentialReference="+fortranArray(potentialsBurkert))
        print("! radius of peak rotation curve = %.16e" % radiusPeakBurkert  )
        print("! peak rotation curve           = %.16e" % velocityPeakBurkert)
        return

    print("Einasto profile (units of rho_0 r_s^3 and G rho_0 r_s^2)")
    print("%-8s %-8s %-22s %-22s" % ("alpha", "x", "M(<x)", "Phi(x)"))
    for alpha, masses, potentials in zip(alphasEinasto, massesEinasto, potentialsEinasto):
        for x, mass, phi in zip(radiiEinasto, masses, potentials):
            print("%-8.2f %-8.2f %-22.14e %-22.14e" % (alpha, x, mass, phi))
    print()
    print("%-8s %-22s %-22s" % ("alpha", "M_total", "r_half-mass"))
    for alpha, massTotal, radiusHalf in zip(alphasEinasto, massesTotalEinasto, radiiHalfMassEinasto):
        print("%-8.2f %-22.14e %-22.14e" % (alpha, massTotal, radiusHalf))
    print()
    print("Burkert profile (units of rho_0 r_s^3 and G rho_0 r_s^2)")
    print("%-10s %-22s %-22s" % ("x", "M(<x)", "Phi(x)"))
    for x, mass, phi in zip(radiiBurkert, massesBurkert, potentialsBurkert):
        print("%-10.0e %-22.14e %-22.14e" % (x, mass, phi))
    print()
    print("Burkert total mass is infinite: rho ~ x^-3 at large x, so M(<x) grows as ln x.")
    print("radius of peak rotation curve = %.16e" % radiusPeakBurkert  )
    print("peak rotation curve           = %.16e" % velocityPeakBurkert)

if __name__ == "__main__":
    main()
