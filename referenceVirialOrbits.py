#!/usr/bin/env python3
# Independent reference values for the virial orbit distributions of Benson (2005) and Jiang et al. (2015), as
# implemented in Galacticus by virialOrbitBenson2005 and virialOrbitJiang2014
# (source/satellites/merging/virial_orbits/{Benson2005,Jiang2014}.F90), for use by the unit test
# source/tests/satellites/virial_orbits.F90.
#
# Nothing here is taken from the Galacticus implementation; each distribution is written from its paper.
#
#  * Benson (2005; MNRAS, 358, 551). Their eqns. (2)-(4) give the joint distribution of the radial and
#    tangential velocities at virial crossing, in units of the host virial velocity,
#
#        f(V_r,V_theta) = a1 V_theta exp[-a2 (V_theta-a9)^2 - b1 (V_r-b2)^2],
#        b1 = a3 exp[-a4 (V_theta-a5)^2],   b2 = a6 exp[-a7 (V_theta-a8)^2],
#
#    with the z=0 coefficients of their Table 2. Galacticus carries unrounded values of those coefficients,
#    which are used here, and samples the distribution over [0,3]^2 - so the moments are taken over that
#    square. Galacticus stores the mean tangential velocity and the root mean squared total velocity as
#    constants; those two numbers are what this script recomputes.
#
#  * Jiang et al. (2015; MNRAS, 448, 1674). Their eqns. (9)-(11) give the distribution of the total velocity
#    at virial crossing as a Voigt profile, and their eqn. (12) the distribution of the radial component,
#    P(V_r/V) = A[exp(B V_r/V) - 1]. Their Table 2 gives (B, gamma, sigma, mu) in three host mass by three
#    mass ratio bins. The mean tangential velocity at fixed total velocity follows in closed form,
#
#        E[V_theta|V] = V pi [B - 2 I_1(B) - 2 L_1(B)] / {4 [1 + B - exp(B)]},
#
#    from integral_0^1 sqrt(1-u^2) exp(B u) du = (pi/2B)[I_1(B) + L_1(B)], with I_1 the modified Bessel
#    function and L_1 the modified Struve function. Galacticus truncates the Voigt profile at five times its
#    half width at half maximum either side of the mean (limited below at zero), using the approximation of
#    Olivero (1977; JQSRT, 17, 233), and renormalizes it over that interval; the same truncation is applied
#    here, since it is part of what is being checked.
#
# All velocities are in units of the host virial velocity under each class' own density contrast definition,
# so no cosmology enters and the reference values are exact.
#
# Andrew Benson (16-September-2026).

import numpy as np
from scipy import integrate, special

# Benson (2005), Table 2 at z=0, as carried (unrounded) by Galacticus.
coefficientsBenson2005=[0.390052e+01,0.247973e+01,0.102373e+02,0.683922e+00,0.353953e+00,0.107716e+01,0.509837e+00,0.206204e+00,0.314641e+00]
velocityMaximumBenson2005=3.0

# Jiang et al. (2015), Table 2. The first index is the host mass bin, the second the satellite-to-host mass
# ratio bin.
bJiang2014    =np.array([[0.049,1.044,2.878],[0.548,1.535,3.946],[1.229,3.396,2.982]])
gammaJiang2014=np.array([[0.109,0.098,0.071],[0.114,0.087,0.030],[0.110,0.050,-0.012]])
sigmaJiang2014=np.array([[0.077,0.073,0.091],[0.094,0.083,0.139],[0.072,0.118,0.187]])
muJiang2014   =np.array([[1.220,1.181,1.100],[1.231,1.201,1.100],[1.254,1.236,1.084]])

def distributionBenson2005(velocityRadial,velocityTangential):
    """The joint velocity distribution of eqns. (2)-(4) of Benson (2005)."""
    a =coefficientsBenson2005
    b1=a[2]*np.exp(-a[3]*(velocityTangential-a[4])**2)
    b2=a[5]*np.exp(-a[6]*(velocityTangential-a[7])**2)
    return a[0]*velocityTangential*np.exp(-a[1]*(velocityTangential-a[8])**2)*np.exp(-b1*(velocityRadial-b2)**2)

def momentsBenson2005():
    """The mean tangential velocity, and the root mean squared total velocity, of the Benson (2005)
    distribution, in units of the host virial velocity."""
    v =velocityMaximumBenson2005
    kwargs=dict(epsabs=1.0e-13,epsrel=1.0e-13)
    normalization,_    =integrate.dblquad(lambda r,t: distributionBenson2005(r,t)             ,0.0,v,0.0,v,**kwargs)
    velocityTangential,_=integrate.dblquad(lambda r,t: distributionBenson2005(r,t)*t          ,0.0,v,0.0,v,**kwargs)
    velocityTotalSquared,_=integrate.dblquad(lambda r,t: distributionBenson2005(r,t)*(r**2+t**2),0.0,v,0.0,v,**kwargs)
    return velocityTangential/normalization,np.sqrt(velocityTotalSquared/normalization),normalization

def profileVoigt(velocity,mu,sigma,gamma):
    """The Voigt profile: the convolution of a Gaussian of width `sigma` with a Lorentzian of half width at
    half maximum `gamma`, centered on `mu`."""
    return special.wofz((velocity-mu+1j*gamma)/(np.sqrt(2.0)*sigma)).real/sigma/np.sqrt(2.0*np.pi)

def limitsVoigt(mu,sigma,gamma):
    """The truncation limits used by Galacticus: five half widths at half maximum either side of the mean,
    limited below at zero, with the half width from the approximation of Olivero (1977)."""
    fullWidthLorentzian=2.0*gamma
    fullWidthGaussian  =2.0*sigma*np.sqrt(2.0*np.log(2.0))
    halfWidth          =0.5*(0.5346*fullWidthLorentzian+np.sqrt(0.2166*fullWidthLorentzian**2+fullWidthGaussian**2))
    return max(mu-5.0*halfWidth,0.0),mu+5.0*halfWidth

def fractionTangentialJiang2014(b):
    """E[V_theta|V]/V for the radial velocity distribution of eqn. (12) of Jiang et al. (2015)."""
    return np.pi*(b-2.0*special.i1(b)-2.0*special.modstruve(1,b))/4.0/(1.0+b-np.exp(b))

def momentsJiang2014(i,j):
    """The mean tangential velocity, and the root mean squared total velocity, for bin (i,j) of Jiang et al.
    (2015), in units of the host virial velocity."""
    mu,sigma,gamma,b=muJiang2014[i,j],sigmaJiang2014[i,j],gammaJiang2014[i,j],bJiang2014[i,j]
    lower,upper     =limitsVoigt(mu,sigma,gamma)
    kwargs          =dict(epsabs=1.0e-14,epsrel=1.0e-13,limit=400)
    normalization,_ =integrate.quad(lambda v: profileVoigt(v,mu,sigma,gamma)       ,lower,upper,**kwargs)
    velocityTotal,_ =integrate.quad(lambda v: profileVoigt(v,mu,sigma,gamma)*v     ,lower,upper,**kwargs)
    velocityTotalSquared,_=integrate.quad(lambda v: profileVoigt(v,mu,sigma,gamma)*v**2,lower,upper,**kwargs)
    return fractionTangentialJiang2014(b)*velocityTotal/normalization,np.sqrt(velocityTotalSquared/normalization)

# Self-checks of this script, independent of anything above.
#  * The Benson (2005) fit is normalized over the square on which it is sampled, to within the precision of
#    its published coefficients.
assert abs(momentsBenson2005()[2]-1.0) < 1.0e-3
#  * As B tends to zero the radial velocity distribution A[exp(B u)-1] tends not to a uniform distribution
#    but to 2u, since exp(B u)-1 -> B u; the mean tangential velocity therefore tends to
#    integral_0^1 2u sqrt(1-u^2) du = 2/3, the isotropic value.
assert abs(fractionTangentialJiang2014(1.0e-4)-2.0/3.0) < 1.0e-4
#  * The closed form agrees with direct quadrature of the distribution.
for bTest in (0.05,1.0,4.0):
    normalizationTest =integrate.quad(lambda u:                  np.exp(bTest*u)-1.0,0.0,1.0)[0]
    tangentialTest    =integrate.quad(lambda u: np.sqrt(1.0-u**2)*(np.exp(bTest*u)-1.0),0.0,1.0)[0]
    assert abs(fractionTangentialJiang2014(bTest)-tangentialTest/normalizationTest) < 1.0e-10
#  * A Voigt profile of vanishing Lorentzian width is a Gaussian.
assert abs(profileVoigt(0.3,0.0,0.5,1.0e-12)-np.exp(-0.5*(0.3/0.5)**2)/0.5/np.sqrt(2.0*np.pi)) < 1.0e-12

if __name__ == "__main__":
    velocityTangential,velocityTotalRootMeanSquared,normalization=momentsBenson2005()
    print("Benson (2005):")
    print(f"  integral of the fit over [0,{velocityMaximumBenson2005:.0f}]^2 = {normalization:.13e}")
    print(f"  mean tangential velocity                = {velocityTangential          :.13e}")
    print(f"  root mean squared total velocity        = {velocityTotalRootMeanSquared:.13e}")
    print()
    print("Jiang et al. (2015):")
    print(f"  {'host':>4s} {'ratio':>5s} {'<V_theta>/V_host':>22s} {'V_rms/V_host':>22s} {'E[V_theta|V]/V':>16s}")
    for i in range(3):
        for j in range(3):
            velocityTangential,velocityTotalRootMeanSquared=momentsJiang2014(i,j)
            print(f"  {i+1:4d} {j+1:5d} {velocityTangential:22.13e} {velocityTotalRootMeanSquared:22.13e} {fractionTangentialJiang2014(bJiang2014[i,j]):16.10f}")
