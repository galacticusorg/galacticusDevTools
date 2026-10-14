#!/usr/bin/env python3
# Reference values for merger and disk instability physics in Galacticus, computed independently from the cited papers using
# astropy constants and scipy. Used to validate `source/tests/mergers_instabilities_physics.F90`.
#
#  * Efstathiou, Lake & Negroponte (1982) bar instability: epsilon = V_peak / sqrt(G M_disk / r_disk), unstable if epsilon <
#    epsilon_c, with epsilon_c interpolated linearly in gas fraction between the stellar (1.1) and gaseous (0.7) thresholds. V_peak
#    is estimated as V(r_disk) times the ratio V_peak/V(r_d) for an isolated thin exponential disk (Freeman 1970), and epsilon is
#    bounded below by its isolated-disk value. The timescale is t_disk [(epsilon_c-epsilon_iso)/(epsilon_c-epsilon)]^2 with
#    t_disk = r_disk/V.
#  * Cole et al. (2000) merger remnant size, eqn. (4.19): (M1+M2)^2/r_new = M1^2/r1 + M2^2/r2 + (f_orbit/c) M1 M2/(r1+r2), with
#    c=0.5, and masses including twice the dark matter mass within each half-mass radius.
# Andrew Benson, Claude (11-September-2026)
import numpy as np
from scipy.special import i0, i1, k0, k1
from scipy.optimize import minimize_scalar
from astropy import constants as const, units as u

G         = const.G.to(u.Mpc*u.km**2/u.s**2/u.Msun).value                     # Mpc (km/s)² / M☉
MpcPerKmS = (u.Mpc/(u.km/u.s)).to(u.Gyr)                                      # Gyr

# Thin exponential disk rotation curve (G=M=r_d=1): V^2(R) = 2 y^2 [I0K0-I1K1](y), y=R/(2 r_d).
v2          = lambda y: 2.0*y**2*(i0(y)*k0(y)-i1(y)*k1(y))
peak        = minimize_scalar(lambda y: -v2(y),bounds=(0.5,2.0),method='bounded',options={'xatol':1.0e-12})
epsilonIso  = np.sqrt(-peak.fun)
boostFactor = epsilonIso/np.sqrt(v2(0.5))

def efstathiou1982(massGas,massStellar,radius,velocity,thresholdStellar=1.1,thresholdGaseous=0.7,timescaleMinimum=1.0e-3):
    massDisk    = massGas+massStellar
    fractionGas = massGas/massDisk
    threshold   = thresholdStellar*(1.0-fractionGas)+thresholdGaseous*fractionGas
    epsilon     = max(epsilonIso,boostFactor*velocity/np.sqrt(G*massDisk/radius))
    if epsilon >= threshold:
        return epsilon, -1.0
    timeDynamical = radius/velocity*MpcPerKmS
    return epsilon, max(timeDynamical,timescaleMinimum)*((threshold-epsilonIso)/(threshold-epsilon))**2

def cole2000(M1,M2,r1,r2,fOrbit=1.0,c=0.5):
    return (M1+M2)**2/(M1**2/r1+M2**2/r2+fOrbit/c*M1*M2/(r1+r2))

if __name__ == "__main__":
    print(f"Isolated thin exponential disk: epsilon_iso = {epsilonIso:.10f}, V_peak/V(r_d) = {boostFactor:.10f}, R_peak/r_d = {2.0*peak.x:.10f}")

    print("\nEfstathiou et al. (1982) bar instability (M_gas=3e9, M_stellar=7e9 M☉, r_d=3e-3 Mpc; thresholds 1.1/0.7, floor 1e-3 Gyr): V [km/s] -> epsilon, timescale [Gyr]")
    for V in (150.0,90.0,10.0):
        epsilon, timescale = efstathiou1982(3.0e9,7.0e9,3.0e-3,V)
        print(f"  {V:6.1f} -> {epsilon:.10e} {timescale:.10e}")

    print("\nCole et al. (2000) remnant size, baryons only (f_orbit=1, c=0.5): M1, M2, r1, r2 -> r_new")
    for M1, M2, r1, r2 in ((1.0,1.0,1.0,1.0),(1.0,1.0e-9,1.0,2.0),(1.0,0.3,1.0,0.5)):
        print(f"  {M1:7.1e} {M2:7.1e} {r1:4.2f} {r2:4.2f} -> {cole2000(M1,M2,r1,r2):.10e}")
