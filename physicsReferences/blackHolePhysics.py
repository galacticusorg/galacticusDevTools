#!/usr/bin/env python3
# Reference values for black hole physics in Galacticus, computed independently from the cited papers and from standard
# results, using astropy constants. Used to validate `source/tests/black_hole_physics.F90`.
#
# Sources:
#  * Kerr ISCO radius, specific energy and angular momentum: Bardeen, Press & Teukolsky (1972, ApJ, 178, 347), eqns. 2.13, 2.12.
#    Evaluated with 50-digit decimal arithmetic so that the near-extremal series used in Galacticus is tested against the exact
#    expressions.
#  * Thin disk radiative efficiency 1-E_ISCO and spin-up s=L_ISCO-2jE_ISCO: Bardeen (1970); Shapiro (2005, eqn. 2 of Benson &
#    Babul 2009).
#  * Binary black hole merger remnant spin: Rezzolla et al. (2008, PRD, 78, 044002; arXiv:0712.3541), eqns. (8), (10), (11), with
#    all spins aligned with the orbital angular momentum, coefficients s4, s5, t0, t2, t3 as quoted in that paper.
#  * Bondi-Hoyle-Lyttleton accretion rate and radius: Edgar (2004, New Astron. Rev., 48, 843), Mdot = 4 pi G^2 M^2 rho /
#    (c_s^2+v^2)^{3/2}, R = G M / c_s^2 (Galacticus' definition of the accretion radius ignores v).
#  * Eddington accretion rate: Mdot_Edd = L_Edd / c^2 = 4 pi G M m_p / (sigma_T c).
#  * Thin disk jet power: Meier (2001, ApJ, 548, L9), eqns. 4 and 5, with the published normalizations 10^41.7 (Schwarzschild) and
#    10^42.7 (Kerr) erg/s, and Galacticus' documented interpolation exp(3.785 j) below j=0.8.
# Andrew Benson, Claude (11-September-2026)
import numpy as np
from decimal import Decimal, getcontext
from astropy import constants as const, units as u

getcontext().prec = 50

# Unit conversions to Galacticus internal units (M☉, Mpc, km/s, Gyr).
G         = const.G.to(u.Mpc*u.km**2/u.s**2/u.Msun).value
c         = const.c.to(u.km/u.s).value
MpcPerKmS = (u.Mpc/(u.km/u.s)).to(u.Gyr)

def cbrt(x):
    return Decimal(0) if x == 0 else (x.ln()/3).exp()

def isco(j):
    """Prograde ISCO radius, specific energy and specific angular momentum (gravitational units)."""
    j  = Decimal(j)
    if j == 1:
        # Extremal limit (0/0 in the closed form).
        return 1.0, float(1/Decimal(3).sqrt()), float(2/Decimal(3).sqrt())
    Z1 = 1+cbrt(1-j**2)*(cbrt(1+j)+cbrt(1-j))
    Z2 = (3*j**2+Z1**2).sqrt()
    r  = 3+Z2-((3-Z1)*(3+Z1+2*Z2)).sqrt()
    x  = r.sqrt()
    r34 = x*x.sqrt()
    E  = (r*x-2*x+j     )/(r34*(r*x-3*x+2*j).sqrt())
    L  = (r**2-2*j*x+j**2)/(r34*(r*x-3*x+2*j).sqrt())
    return float(r), float(E), float(L)

def rezzolla2008(massA,massB,spinA,spinB):
    s4, s5, t0, t2, t3 = -0.129, -0.384, -2.686, -3.454, 2.353
    m1, m2, a1, a2 = (massA, massB, spinA, spinB) if massA >= massB else (massB, massA, spinB, spinA)
    q  = m2/m1
    nu = q/(1.0+q)**2
    l  = (s4/(1.0+q**2)**2*(a1**2+a2**2*q**4+2.0*a1*a2*q**2)
          +(s5*nu+t0+2.0)/(1.0+q**2)*(a1+a2*q**2)
          +2.0*np.sqrt(3.0)+t2*nu+t3*nu**2)                                         # (10), (11)
    a  = np.sqrt(a1**2+a2**2*q**4+2.0*a2*a1*q**2+2.0*(a1+a2*q**2)*l*q+l**2*q**2)/(1.0+q)**2 # (8)
    return m1+m2, a

def soundSpeed(T):
    # Monatomic ideal gas of primordial composition (mean atomic mass computed below).
    return np.sqrt(5.0/3.0*const.k_B.value*T/muPrimordial/const.u.value)/1.0e3     # km/s

def bondiHoyleRate(M,rho,v,T,radius=None):
    cs = soundSpeed(T)
    if radius is None:
        rate = 4.0*np.pi*(G*M)**2*rho/(cs**2+v**2)**1.5                            # M☉ km/s / Mpc
    else:
        rate = 4.0*np.pi*radius**2*rho*np.sqrt(cs**2+v**2)
    return rate/MpcPerKmS                                                            # M☉/Gyr

def eddingtonRate(M):
    return (4.0*np.pi*const.G*M*u.Msun*const.m_p/const.sigma_T/const.c).to(u.Msun/u.Gyr).value

def meierJetPower(M,Mdot,j):
    mdot = Mdot/eddingtonRate(M)
    m9   = M/1.0e9
    if j > 0.8:
        P = 10.0**42.7*m9**0.9*mdot**1.2*(1.0+1.1*j+0.29*j**2)
    else:
        P = 10.0**41.7*m9**0.9*mdot**1.2*np.exp(3.785*j)
    return (P*u.erg/u.s*u.Gyr/u.Msun).to(u.km**2/u.s**2).value                      # M☉ (km/s)^2 / Gyr per M☉ of... i.e. internal units

if __name__ == "__main__":
    # Mean particle mass of fully ionized primordial gas, mu = 1/(2X/A_H+3Y/A_He), which is what Galacticus'
    # `meanAtomicMassPrimordial` represents, using Galacticus' primordial abundances X=0.7514, Y=0.2486 (Cyburt et al. 2008) and
    # its isotope masses for ¹H and ⁴He.
    import sys
    muPrimordial = float(sys.argv[1]) if len(sys.argv) > 1 else 1.0/(2.0*0.7514/1.0078250322+3.0*0.2486/4.0026032545)
    print(f"mu_primordial = {muPrimordial:.10f}")

    print("\nISCO (prograde): j, r_ISCO, E_ISCO, L_ISCO, efficiency=1-E, s=L-2jE")
    # j=0.9999 is the maximum spin allowed by Galacticus' standard black hole component.
    for j in ("0.0","0.3","0.6","0.9","0.99","0.999","0.9999","0.99999","0.999995","1.0"):
        r, E, L = isco(j)
        print(f"  {j:>9s} {r:.10e} {E:.10e} {L:.10e} {1.0-E:.10e} {L-2.0*float(j)*E:.10e}")

    print("\nFrame-dragging (ZAMO) angular velocity in the equatorial plane, omega=-g_tphi/g_phiphi (Boyer-Lindquist, G=c=M=1): j, r -> omega")
    for j, r in ((0.5,2.0),(0.9,2.3208830418),(0.99,1.5)):
        g_tphi   = -2.0*j/r
        g_phiphi = r**2+j**2+2.0*j**2/r
        print(f"  {j:4.2f} {r:.10f} -> {-g_tphi/g_phiphi:.10e}")

    print("\nRezzolla 2008: mA, mB, aA, aB -> m_fin, a_fin")
    for mA, mB, aA, aB in ((1.0,1.0,0.0,0.0),(1.0,1.0,0.5,0.5),(1.0,1.0,0.9,0.9),(1.0,0.5,0.0,0.7),(0.5,1.0,0.7,0.0),
                           (1.0,0.1,0.8,0.3),(1.0,1.0e-6,0.6,0.9),(3.0,1.0,0.99,0.99)):
        mf, af = rezzolla2008(mA,mB,aA,aB)
        print(f"  {mA:7.1e} {mB:7.1e} {aA:4.2f} {aB:4.2f} -> {mf:.10e} {af:.10e}")

    print("\nBondi-Hoyle-Lyttleton (M=1e8 M☉): T [K], rho [M☉/Mpc³], v [km/s], radius [Mpc] -> c_s [km/s], R_BHL [Mpc], Mdot [M☉/Gyr]")
    for T, rho, v, radius in ((1.0e2,1.0e18,0.0,None),(1.0e2,1.0e18,50.0,None),(1.0e7,1.0e15,0.0,None),(1.0e7,1.0e15,0.0,1.0e-3)):
        cs = soundSpeed(T)
        print(f"  {T:7.1e} {rho:7.1e} {v:5.1f} {radius} -> {cs:.10e} {G*1.0e8/cs**2:.10e} {bondiHoyleRate(1.0e8,rho,v,T,radius):.10e}")
    print(f"\nJeans length (T=1e4 K, rho=1e15 M☉/Mpc³) = {soundSpeed(1.0e4)/np.sqrt(G*1.0e15):.10e} Mpc")

    print(f"\nEddington accretion rate (M=1e8 M☉) = {eddingtonRate(1.0e8):.10e} M☉/Gyr")

    print("\nMeier (2001) thin disk jet power (M=1e9 M☉, Mdot=1e8 M☉/Gyr): j -> P [M☉ (km/s)² / Gyr]")
    for j in (0.0,0.5,0.8,0.9,0.99):
        print(f"  {j:4.2f} -> {meierJetPower(1.0e9,1.0e8,j):.10e}")
