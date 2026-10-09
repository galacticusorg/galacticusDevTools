#!/usr/bin/env python3
"""Independent reference velocity dispersions for the Zhao (1996) mass distribution.

Galacticus evaluates the 1D velocity dispersion of a self-gravitating Zhao (1996) profile from
closed-form solutions for four special cases of (alpha,beta,gamma) = (1,3,gamma), with gamma in
{0, 1/2, 1, 3/2}. Each is implemented as three branches: a series for small radii, a full solution,
and a series for large radii, switching at r/r_s = 1e-3 and 1e2. This script instead integrates the
isotropic Jeans equation numerically, so all twelve branches can be checked against something which
shares none of their algebra.

Everything is scale-free (rho_0 = r_s = G = 1), so the quantity returned is

    Q(x) = sigma^2 / (G rho_0 r_s^2),

which is what Galacticus computes internally before multiplying by sqrt(G rho_0) r_s.

Two numerical points matter, both of which give badly wrong answers if ignored:

  * The outer Jeans integral runs to infinity and its integrand decays only as (ln s)/s^4. It is
    taken in log space, s = x e^t; truncating at a large finite radius instead is not adequate.
  * The full closed-form solutions lose accuracy catastrophically at large radius through
    cancellation - the NFW one is wrong by a factor of 240 at x = 1e4 - which is exactly why the
    large-radius series exist. A reference built by comparing against those closed forms would
    therefore condemn the series wrongly; it must be built from the Jeans integral.

Usage:  ./zhao1996DispersionCheck.py [--validate] [--fortran]
"""
import argparse
import math

from scipy.integrate import quad

tolerance = 1.0e-13
gammas    = [0.0, 0.5, 1.0, 1.5]
# Radii spanning all three branches: below 1e-3, between, and above 1e2.
radii     = [1.0e-5, 1.0e-4, 1.0e-3, 1.0e-2, 1.0e-1, 1.0e0, 1.0e1, 1.0e2, 1.0e3, 1.0e4]

def density(x, gamma):
    return x**(-gamma)*(1.0+x)**(gamma-3.0)

def mass(s, gamma):
    """4 pi int_0^s t^(2-gamma) (1+t)^(gamma-3) dt, split at t=1 and taken in log space above it."""
    inner = quad(lambda t: t**(2.0-gamma)*(1.0+t)**(gamma-3.0), 0.0, min(s, 1.0),
                 limit=400, epsabs=0.0, epsrel=tolerance)[0]
    outer = 0.0
    if s > 1.0:
        outer = quad(lambda u: (lambda t: t**(2.0-gamma)*(1.0+t)**(gamma-3.0)*t)(math.exp(u)),
                     0.0, math.log(s), limit=400, epsabs=0.0, epsrel=tolerance)[0]
    return 4.0*math.pi*(inner+outer)

def dispersionSquared(x, gamma):
    """Q(x) = sigma^2/(G rho_0 r_s^2) from the isotropic Jeans equation."""
    integrand = lambda t: (lambda s: density(s, gamma)*mass(s, gamma)/s**2*s)(x*math.exp(t))
    return quad(integrand, 0.0, 60.0, limit=800, epsabs=0.0, epsrel=1.0e-11)[0]/density(x, gamma)

def validate():
    """Check against the exact NFW result, for which the density and mass are elementary."""
    def exact(x):
        integrand = lambda t: (lambda s: 4.0*math.pi*(math.log1p(s)-s/(1.0+s))/(s**3*(1.0+s)**2)*s)(x*math.exp(t))
        return x*(1.0+x)**2*quad(integrand, 0.0, 60.0, limit=800, epsabs=0.0, epsrel=tolerance)[0]
    print("Validation against the exact gamma = 1 (NFW) solution")
    print("  %-10s %-16s %-16s %-10s" % ("x", "reference", "exact", "rel. diff"))
    for x in radii:
        reference, exactValue = dispersionSquared(x, 1.0), exact(x)
        print("  %-10.0e %-16.8e %-16.8e %-10.1e" % (x, reference, exactValue, abs(reference-exactValue)/exactValue))

def fortranArray(values):
    return "[" + ",".join(("%.14e" % v).replace("e", "d") for v in values) + "]"

def main():
    parser = argparse.ArgumentParser(description="Reference velocity dispersions for the Zhao (1996) profile.")
    parser.add_argument("--validate", action="store_true", help="check the reference against the exact NFW solution")
    parser.add_argument("--fortran" , action="store_true", help="emit Fortran array constructors")
    arguments = parser.parse_args()
    if arguments.validate:
        validate()
        return
    values = [[dispersionSquared(x, gamma) for x in radii] for gamma in gammas]
    if arguments.fortran:
        print("radii ="+fortranArray(radii))
        for gamma, row in zip(gammas, values):
            print("! gamma = %.1f" % gamma)
            print("dispersionSquaredReference="+fortranArray(row))
        return
    print("%-8s %-10s %-22s" % ("gamma", "x", "sigma^2/(G rho_0 r_s^2)"))
    for gamma, row in zip(gammas, values):
        for x, value in zip(radii, row):
            print("%-8.1f %-10.0e %-22.14e" % (gamma, x, value))

if __name__ == "__main__":
    main()
