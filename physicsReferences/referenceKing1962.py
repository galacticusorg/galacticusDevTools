#!/usr/bin/env python3
# Independent reference values for the King (1962) satellite tidal radius, as implemented in Galacticus by
# satelliteTidalStrippingRadiusKing1962 (source/satellites/tidal_stripping/radius/King1962.F90), for use by
# the unit test source/tests/satellites/tidal_stripping/radius/King1962.F90.
#
# Nothing here is taken from the Galacticus implementation. The tidal radius is that of King (1962; AJ, 67,
# 471), generalized in the usual way to an extended satellite in an extended host: r_t solves
#
#     G M_sat(<r_t) / r_t^3 = gamma omega^2 - d^2 Phi_host / dR^2,
#
# where omega = |R x V| / R^2 is the orbital angular velocity, gamma is the efficiency of the centrifugal term,
# and for a spherical host d^2 Phi/dR^2 = 4 pi G rho_host(R) - 2 G M_host(<R) / R^3. For a point-mass host on a
# circular orbit this gives the Jacobi radius, r_t = R (m / 3 M)^(1/3), which is checked below as a test of
# this script itself. When the right-hand side is not positive (a compressive tidal field) there is no tidal
# radius, and Galacticus instead returns the radius enclosing the bound dark matter mass, capped at the virial
# radius: that fallback is also computed here.
#
# Both halos are NFW profiles, truncated at nothing (the NFW form is used at all radii), with virial radii
# defined by the Bryan & Norman (1998; ApJ, 495, 80) flat-universe density contrast relative to the mean
# matter density at z=0. As the test uses the "darkMatterOnly" profile class, both mass distributions are
# scaled by the dark matter fraction, f_DM = 1 - Omega_b / Omega_m.
#
# Units are Galacticus internal units: M_sun, Mpc, km/s. The physical constants are those of GSL
# (gsl_const_mksa.h), from which Galacticus builds its own, so that no difference in constants enters the
# comparison.
#
# Andrew Benson, Claude (2026)

import math
from scipy.optimize import brentq

# Physical constants (GSL MKSA values).
gravitationalConstantSI = 6.673e-11        # m^3 kg^-1 s^-2
massSolar               = 1.98892e30       # kg
parsec                  = 3.08567758135e16 # m
megaParsec              = 1.0e6*parsec
kilo                    = 1.0e3
G                       = gravitationalConstantSI*massSolar/kilo**2/megaParsec # Mpc (km/s)^2 / M_sun

# Cosmology (must match testSuite/parameters/satellites/tidalStrippingRadiusKing1962.xml).
HubbleConstant  = 67.36
OmegaMatter     = 0.3153
OmegaBaryon     = 0.0493
OmegaDarkEnergy = 0.6847
fractionDark    = 1.0-OmegaBaryon/OmegaMatter

# Halos (must match the unit test).
massHost        = 1.0e12  # M_sun
radiusScaleHost = 2.5e-2  # Mpc
massSat         = 1.0e10  # M_sun
radiusScaleSat  = 4.0e-3  # Mpc

def radiusVirial(mass):
    """Virial radius for the Bryan & Norman (1998) flat-universe density contrast at z=0."""
    densityCritical = 3.0*HubbleConstant**2/8.0/math.pi/G
    densityMean     = OmegaMatter*densityCritical
    x               = OmegaMatter-1.0
    densityContrast = (18.0*math.pi**2+82.0*x-39.0*x**2)/(x+1.0) # Relative to the mean density.
    return (3.0*mass/4.0/math.pi/densityContrast/densityMean)**(1.0/3.0)

class NFW:
    """An NFW profile of given virial mass and scale radius, scaled by a mass factor."""
    def __init__(self,mass,radiusScale,factorMass):
        self.radiusScale = radiusScale
        self.factorMass  = factorMass
        self.radiusVir   = radiusVirial(mass)
        c                = self.radiusVir/radiusScale
        self.densityNorm = mass/(4.0*math.pi*radiusScale**3*self.mu(c))
    @staticmethod
    def mu(x):
        return math.log(1.0+x)-x/(1.0+x)
    def massEnclosed(self,r):
        return self.factorMass*4.0*math.pi*self.densityNorm*self.radiusScale**3*self.mu(r/self.radiusScale)
    def density(self,r):
        x = r/self.radiusScale
        return self.factorMass*self.densityNorm/x/(1.0+x)**2

host      = NFW(massHost,radiusScaleHost,fractionDark)
satellite = NFW(massSat ,radiusScaleSat ,fractionDark)

def cross(a,b):
    return [a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]]

def norm(a):
    return math.sqrt(sum(ai**2 for ai in a))

def tidalPull(position,velocity,efficiencyCentrifugal):
    """gamma omega^2 - d^2 Phi/dR^2 for the host, in (km/s/Mpc)^2."""
    R                 = norm(position)
    frequencyAngular  = norm(cross(position,velocity))/R**2
    potentialSecondDerivative = 4.0*math.pi*G*host.density(R)-2.0*G*host.massEnclosed(R)/R**3
    return efficiencyCentrifugal*frequencyAngular**2-potentialSecondDerivative

def radiusTidal(position,velocity,efficiencyCentrifugal):
    pull = tidalPull(position,velocity,efficiencyCentrifugal)
    assert pull > 0.0
    f    = lambda r: G*satellite.massEnclosed(r)/r**3-pull
    return brentq(f,1.0e-8,1.0e2,xtol=1.0e-14,rtol=1.0e-14)

def radiusFallback(massBound):
    """No tidal radius exists: the radius enclosing the bound dark matter mass, capped at the virial radius."""
    massBoundDark = massBound*fractionDark
    if massBoundDark >= satellite.massEnclosed(satellite.radiusVir):
        return satellite.radiusVir
    f = lambda r: satellite.massEnclosed(r)-massBoundDark
    return brentq(f,1.0e-10,satellite.radiusVir,xtol=1.0e-14,rtol=1.0e-14)

# Self-check: for a point-mass host and point-mass satellite on a circular orbit the construction above must
# give the Jacobi radius exactly.
def jacobiCheck():
    M, m, R = 1.0e12, 1.0e9, 0.1
    omega2  = G*M/R**3
    pull    = omega2-(-2.0*G*M/R**3)
    rt      = (G*m/pull)**(1.0/3.0)
    rJacobi = R*(m/3.0/M)**(1.0/3.0)
    assert abs(rt/rJacobi-1.0) < 1.0e-14, (rt,rJacobi)
jacobiCheck()

# Test cases. Each is (label, position [Mpc], velocity [km/s], gamma).
cases = [
    ("tangential orbit, R=100 kpc"       , [0.10 ,0.00 , 0.00], [  0.0,150.0,0.0], 1.0),
    ("radial orbit, R=100 kpc"           , [0.10 ,0.00 , 0.00], [150.0,  0.0,0.0], 1.0),
    ("tangential orbit, gamma=0"         , [0.10 ,0.00 , 0.00], [  0.0,150.0,0.0], 0.0),
    ("tangential orbit, R=30 kpc"        , [0.03 ,0.00 , 0.00], [  0.0,200.0,0.0], 1.0),
    ("general orbit, gamma=0.5"          , [0.10 ,0.12 ,-0.05], [100.0,120.0,0.0], 0.5),
]

print(f"# G = {G:.10e} Mpc (km/s)^2 / M_sun; f_DM = {fractionDark:.10f}")
print(f"# r_vir(host) = {host.radiusVir:.10e} Mpc, r_vir(satellite) = {satellite.radiusVir:.10e} Mpc")
print("# Tidal radii (main branch):")
for label,position,velocity,gamma in cases:
    print(f"#   {label:35s} pull = {tidalPull(position,velocity,gamma):.6e} (km/s/Mpc)^2, r_t = {radiusTidal(position,velocity,gamma):.10e} Mpc")
print("# Fallback radii (no tidal radius):")
for fraction in (0.5,0.9,1.1):
    print(f"#   m_bound = {fraction:.1f} m_sat: r = {radiusFallback(fraction*massSat):.10e} Mpc")
# Fortran-ready arrays.
print("radiusTidalReference   =[" + ",".join(f"{radiusTidal(p,v,g):.10e}".replace("e","d") for _,p,v,g in cases) + "]")
print("radiusFallbackReference=[" + ",".join(f"{radiusFallback(f*massSat):.10e}".replace("e","d") for f in (0.5,0.9,1.1)) + "]")
