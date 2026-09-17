#!/usr/bin/env python3
"""Independent reference values for the Meiksin (2006) intergalactic attenuation model.

Written from the equations of Meiksin (2006; MNRAS 365, 807; arXiv:astro-ph/0512435) for the
Galacticus unit test `tests.spectra.postprocess.Meiksin2006`.

The transmission is exp(-tau), with tau accumulated from three contributions:

  * Lyman-series lines, n = 2..31, each included only where the line redshift falls in range;
  * Poisson-distributed optically thick (Lyman limit) systems;
  * optically thin systems.

The Lyman limit term is the delicate one. Meiksin's equation is

  tau_LLS = N0/(4+g-3b) [ Gamma(2-b,1) - e^-1 - sum_{n=0..inf} (b-1)(-1)^n / ((n+1-b) n!) ]
                        x [ (1+z)^(-3(b-1)+g+1) X^(3(b-1)) - X^(g+1) ]
          - N0 sum_{n=1..inf} (b-1)(-1)^n / ((3n-g-1)(n+1-b) n!)
                        x [ (1+z)^(g+1-3n) X^(3n) - X^(g+1) ]

with X = lambda_observed/lambda_LymanLimit, N0 = 0.25, b = beta = 1.5, g = gamma = 1.5. Three
details of it are easy to get wrong, and getting any of them wrong is partly masked by the others:

  1. Gamma(2-b,1) is the *incomplete* Gamma function, not Gamma(2-b).
  2. The signs alternate as (-1)^n. In Fortran this must be written `(-1)**n`: `**` binds more
     tightly than unary minus, so `-1**n` is -1 for every n.
  3. The two sums do not start at the same term - the first runs from n=0, the second from n=1.

With all three right the bracket in the first term reduces analytically to Gamma(2-b), since
  sum_{n=0..inf} (b-1)(-1)^n/((n+1-b) n!) = (b-1) gammaLower(1-b,1) = -[gammaLower(2-b,1) + e^-1]
by the recurrence gammaLower(a,x) = [gammaLower(a+1,x) + x^a e^-x]/a, so the bracket is
Gamma(2-b,1) + gammaLower(2-b,1) = Gamma(2-b). `--self-check` verifies this, and it is a useful
check on any reimplementation.

The transmission must satisfy 0 < T <= 1 everywhere. That bound is what exposes an incorrect
treatment of these terms: correcting the sign alone, without the other two, drives tau negative and
T above unity over a large part of the plane.

Usage:  ./meiksin2006Check.py [--self-check] [--fortran]
"""
import argparse
import math

from scipy.special import gamma as gammaFunction, gammaincc, gammainc

N0            = 0.25
beta          = 1.5
gammaExponent = 1.5
countSeries   = 10    # Meiksin notes ten terms give high convergence.

# The reference grid. Wavelengths are given as X = lambda_observed/lambda_LymanLimit, expressed as a
# fraction of (1+z) so that each redshift covers the same three regimes: the Lyman continuum
# (f < 1), the Lyman series alone (1 < f < 4/3) and no absorption at all (f > 4/3).
redshifts = [1.0, 2.0, 3.0, 5.0]
fractions = [0.30, 0.60, 0.90, 1.05, 1.20, 1.40]

def gammaIncompleteUpper(a, x):
    return gammaFunction(a)*gammaincc(a, x)

def opticalDepth(X, redshift):
    """Effective optical depth at observed wavelength X (in units of the Lyman limit wavelength)."""
    if redshift <= 0.0:
        return 0.0
    tauLine      = [0.0]*32
    redshiftLine = [0.0]*32
    for n in range(3, 10):
        redshiftLine[n] = X*(1.0-1.0/n**2)-1.0
    tauLine[2] = 1.0
    for n, coefficient in ((3, 0.348), (4, 0.179), (5, 0.109)):
        exponent   = 0.3333 if redshiftLine[n] < 3.0 else 0.1667
        tauLine[n] = coefficient*(0.25*(1.0+redshiftLine[n]))**exponent
    for n, coefficient in ((6, 0.0722), (7, 0.0508), (8, 0.0373), (9, 0.0283)):
        tauLine[n] = coefficient*(0.25*(1.0+redshiftLine[n]))**0.3333
    for n in range(10, 32):
        tauLine[n] = tauLine[9]*720.0/n/(n**2-1)
    coefficient, exponent = (0.00211, 3.70) if redshift <= 4.0 else (0.00058, 4.50)
    for n in range(2, 32):
        tauLine[n] *= coefficient*(X*(1.0-1.0/n**2))**exponent
    tau = sum(tauLine[n] for n in range(2, 32) if X < (1.0+redshift)/(1.0-1.0/n**2))
    if X < 1.0+redshift:
        seriesA = sum( float((-1)**n)*(beta-1.0)
                      /(n+1.0-beta)/math.factorial(n)
                      for n in range(0, countSeries))
        seriesB = sum( float((-1)**n)*(beta-1.0)
                      *((1.0+redshift)**(gammaExponent+1.0-3.0*n)*X**(3.0*n)-X**(gammaExponent+1.0))
                      /(n+1.0-beta)/(3.0*n-gammaExponent-1.0)/math.factorial(n)
                      for n in range(1, countSeries))
        tau += ( N0
                *(gammaIncompleteUpper(2.0-beta, 1.0)-math.exp(-1.0)-seriesA)
                *((1.0+redshift)**(-3.0*(beta-1.0)+gammaExponent+1.0)*X**(3.0*(beta-1.0))-X**(gammaExponent+1.0))
                /(4.0+gammaExponent-3.0*beta)
               -N0*seriesB)
        tau += 0.805*X**3*(1.0/X-1.0/(1.0+redshift))
    return tau

def transmission(X, redshift):
    return math.exp(-opticalDepth(X, redshift))

def selfCheck():
    seriesA = sum(float((-1)**n)*(beta-1.0)/(n+1.0-beta)/math.factorial(n) for n in range(countSeries))
    bracket = gammaIncompleteUpper(2.0-beta, 1.0)-math.exp(-1.0)-seriesA
    print("Bracket of the Lyman-limit term")
    print("  computed from the series : %.14f" % bracket)
    print("  identity, Gamma(2-beta)  : %.14f" % gammaFunction(2.0-beta))
    print("  difference               : %.3e  (the %d-term truncation)" % (abs(bracket-gammaFunction(2.0-beta)), countSeries))
    countViolation, worst = 0, 0.0
    redshift = 0.05
    while redshift <= 7.0:
        X = 0.05
        while X <= 3.0*(1.0+redshift):
            value = transmission(X, redshift)
            if value > 1.0+1.0e-12:
                countViolation += 1
                worst           = max(worst, value)
            X += 0.01
        redshift += 0.05
    print("Transmission bound 0 < T <= 1: %d violations (worst %.4g)" % (countViolation, worst))

def fortranArray(values):
    return "[" + ",".join(("%.14e" % v).replace("e", "d") for v in values) + "]"

def main():
    parser = argparse.ArgumentParser(description="Reference values for the Meiksin (2006) IGM attenuation model.")
    parser.add_argument("--self-check", action="store_true", help="verify the analytic identity and the transmission bound")
    parser.add_argument("--fortran"   , action="store_true", help="emit Fortran array constructors")
    arguments = parser.parse_args()
    if arguments.self_check:
        selfCheck()
        return
    values = [[transmission(f*(1.0+z), z) for f in fractions] for z in redshifts]
    if arguments.fortran:
        print("redshifts          ="+fortranArray(redshifts))
        print("wavelengthFractions="+fortranArray(fractions))
        for z, row in zip(redshifts, values):
            print("! z = %.1f" % z)
            print("transmissionReference="+fortranArray(row))
        return
    print("%-8s %-10s %-10s %-22s" % ("z", "f", "X", "transmission"))
    for z, row in zip(redshifts, values):
        for f, value in zip(fractions, row):
            print("%-8.1f %-10.2f %-10.4f %-22.14e" % (z, f, f*(1.0+z), value))

if __name__ == "__main__":
    main()
