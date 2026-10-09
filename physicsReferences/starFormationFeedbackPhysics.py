#!/usr/bin/env python3
# Reference values for star formation and stellar feedback physics in Galacticus, computed independently from the documented
# formulae and cited papers using astropy constants and scipy quadrature. Used to validate
# `source/tests/star_formation_feedback_physics.F90`.
#
#  * Kennicutt-Schmidt star formation rate surface density: Kennicutt (1998, ApJ, 498, 541), eqn. 4, applied to the hydrogen gas
#    surface density (Kennicutt's gas surface densities exclude helium), with the critical density truncation Sigma_crit = q kappa
#    sigma / (pi G), kappa = sqrt(2) V / r (Kennicutt 1989).
#  * Disk-integrated star formation rate: Mdot = 2 pi int_0^{10 r_d} r Sigmadot(r) dr, for an exponential disk. For an untruncated
#    power-law law this has the closed form 2 pi A (x_H Sigma_0)^N (r_d/N)^2 [1 - (1+10N) exp(-10N)].
#  * Dynamical time star formation timescale: tau = tau_dyn (V/200 km/s)^alpha / epsilon, tau_dyn = r/V, with a floor.
#  * Power-law outflows: Mdot = (V_outflow/V)^alpha Edot / E_canonical.
#  * Rate-limited outflows: the total outflow rate is limited to M_gas / (f tau_dyn).
# Andrew Benson, Claude (11-September-2026)
import numpy as np
from scipy.integrate import quad
from astropy import constants as const, units as u

G         = const.G.to(u.Mpc*u.km**2/u.s**2/u.Msun).value                     # Mpc (km/s)² / M☉
MpcPerKmS = (u.Mpc/(u.km/u.s)).to(u.Gyr)                                      # Gyr
Ecanonical= 4.517e5                                                            # M☉ (km/s)² per M☉ (Galacticus definition)

# Test disk: metal-free gas (so x_H is the primordial hydrogen mass fraction), exponential surface density profile.
xH        = 0.7514
massGas   = 1.0e10                                                             # M☉
radiusDisk= 3.0e-3                                                             # Mpc (exponential scale length)
velocity  = 150.0                                                              # km/s

def surfaceDensityGas(r):
    return massGas/(2.0*np.pi*radiusDisk**2)*np.exp(-r/radiusDisk)             # M☉/Mpc²

def kennicuttSchmidt(r,A=0.147,N=1.4,truncate=True,exponentTruncated=6.0,sigma=10.0,q=0.4):
    # A in M☉/Gyr/pc² for surface densities in M☉/pc²; result in M☉/Gyr/Mpc².
    SigmaH_pc = xH*surfaceDensityGas(r)/1.0e12                                  # M☉/pc²
    rate      = A*SigmaH_pc**N*1.0e12
    if truncate:
        if r <= 0.0:
            return 0.0
        SigmaCrit = q*np.sqrt(2.0)*velocity/r*sigma/(np.pi*G)                  # M☉/Mpc²
        if surfaceDensityGas(r) < SigmaCrit:
            rate *= (surfaceDensityGas(r)/SigmaCrit)**exponentTruncated
    return rate

def integratedRate(truncate):
    # Split the range to help the quadrature resolve the truncation.
    edges = np.linspace(0.0,10.0*radiusDisk,41)
    total = sum(quad(lambda r: r*kennicuttSchmidt(r,truncate=truncate),a,b,epsabs=0.0,epsrel=1.0e-12,limit=200)[0] for a, b in zip(edges[:-1],edges[1:]))
    return 2.0*np.pi*total

if __name__ == "__main__":
    print(f"Test disk: M_gas={massGas:.3e} M☉, r_d={radiusDisk:.3e} Mpc, V={velocity:.1f} km/s, x_H={xH}")

    print("\nKennicutt-Schmidt (A=0.147, N=1.4, truncated with alpha=6, sigma=10 km/s, q=0.4): r/r_d -> Sigmadot [M☉/Gyr/Mpc²]")
    for x in (0.5,1.0,3.0,6.0):
        print(f"  {x:4.1f} -> truncated={kennicuttSchmidt(x*radiusDisk):.10e} untruncated={kennicuttSchmidt(x*radiusDisk,truncate=False):.10e}")

    N      = 1.4
    Sigma0 = xH*massGas/(2.0*np.pi*radiusDisk**2)/1.0e12
    closed = 2.0*np.pi*0.147*1.0e12*Sigma0**N*(radiusDisk/N)**2*(1.0-(1.0+10.0*N)*np.exp(-10.0*N))
    print(f"\nIntegrated SFR, untruncated: closed form = {closed:.10e}, quadrature = {integratedRate(False):.10e} M☉/Gyr")
    print(f"Integrated SFR, truncated  : quadrature  = {integratedRate(True):.10e} M☉/Gyr")

    print("\nDynamical time timescale (epsilon=0.04, alpha=2, floor 1e-3 Gyr): r [Mpc], V [km/s] -> tau [Gyr]")
    for r, V in ((radiusDisk,velocity),(1.0e-3,300.0),(1.0e-6,300.0)):
        tauDyn = r/V*MpcPerKmS
        print(f"  {r:.3e} {V:6.1f} -> tau_dyn={tauDyn:.10e} tau={max(tauDyn*(V/200.0)**2/0.04,1.0e-3):.10e}")

    print("\nPower-law outflow (V_outflow=250 km/s, alpha=2) and rate limit (f=0.001): Edot [M☉ (km/s)²/Gyr] -> Mdot [M☉/Gyr]")
    tauDyn = radiusDisk/velocity*MpcPerKmS
    rateMaximum = massGas/tauDyn/1.0e-3
    for Edot in (1.0e14,1.0e20):
        rate = (250.0/velocity)**2*Edot/Ecanonical
        print(f"  {Edot:.1e} -> powerLaw={rate:.10e} rateLimit={min(rate,rateMaximum):.10e} (maximum {rateMaximum:.10e})")
