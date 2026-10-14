#!/usr/bin/env python3
# Independent reference values for the molecular fraction and star formation rate surface density laws of
# Blitz & Rosolowsky (2006) and Krumholz, McKee & Tumlinson (2009), as implemented in Galacticus by
# starFormationRateSurfaceDensityDisksBlitz2006 and starFormationRateSurfaceDensityDisksKrumholz2009
# (source/star_formation/rate_surface_density/disks/{Blitz2006,Krumholz2009}.F90), for use by the unit test
# source/tests/star_formation/molecular_fractions.F90.
#
# Nothing here is taken from the Galacticus implementation - every expression is written directly from the
# papers:
#
#  * Blitz & Rosolowsky (2006; ApJ, 650, 933). Their eqn. (11) gives the ratio of molecular to atomic
#    hydrogen surface density as R_mol = (P_ext/P_0)^alpha, and their eqn. (21) the molecular fraction as
#    f_H2 = R_mol/(1+R_mol). Their Table 2 (and eqn. 12) gives the "Mean" fit, alpha = 0.92 with
#    P_0/k_B = 3.5e4 K/cm^3. The midplane pressure of a disk of locally isothermal gas and stars is
#
#        P_ext = (pi/2) G Sigma_gas [Sigma_gas + (sigma_gas/sigma_star) Sigma_star],
#
#    with sigma_star = sqrt(pi G h_star Sigma_star) for a stellar scale height h_star. The star formation
#    rate surface density then follows the Leroy et al. (2008) form used by Galacticus,
#
#        SigmaDot_star = nu_SF f_H2 Sigma_H,  nu_SF = nu_0 [1 + (Sigma_H/Sigma_0)^q],
#
#    where Sigma_H = X_H Sigma_gas is the hydrogen surface density.
#
#  * Krumholz, McKee & Tumlinson (2009; ApJ, 699, 850). Their eqn. (2) gives the molecular fraction,
#
#        f_H2 = 1 - [1 + (3 s / (4 (1+delta)))^-5]^-1/5,
#        s = ln(1 + 0.6 chi + 0.01 chi^2) / (0.04 Sigma_comp,0 Z'),
#        chi = 0.77 (1 + 3.1 Z'^0.365),  delta = 0.0712 (0.1/s + 0.675)^-2.8,
#
#    with Sigma_comp = c Sigma_gas the surface density of a molecular complex, and their eqn. (10) the star
#    formation rate surface density,
#
#        SigmaDot_star = f_H2 Sigma_gas / (2.6 Gyr) * (Sigma_gas/85 Msun pc^-2)^-+0.33,
#
#    the exponent being -0.33 below the transition surface density and +0.33 above it. Sigma_gas is the
#    *total* gas surface density in both, including helium (their eqn. 1 and the caption of their Fig. 1).
#    Their eqn. (11) of McKee & Krumholz (2010) fast approximation, f_H2 = 1 - 0.75 s/(1+0.25 s) for s < 2,
#    is also given here.
#
# The disk is exponential, Sigma(R) = M/(2 pi R_d^2) exp(-R/R_d), which is what the unit test's
# "exponentialDisk" mass distribution provides, but is computed here directly.
#
# Physical constants are those of GSL (gsl_const_mksa.h), from which Galacticus builds its own, so that no
# difference in constants enters the comparison. Galacticus' hydrogen mass fraction is interpolated linearly
# in metallicity between its primordial and Solar values, X_H = X_p + (Z/Z_sun) (X_sun - X_p); that
# definition, and the Solar metallicity Z_sun, are conventions of the code rather than of either paper, so
# they are taken from Galacticus' constants here.
#
# Andrew Benson (15-September-2026).

import math

# GSL physical constants (gsl_const_mksa.h).
gravitationalConstant = 6.673e-11          # m^3/kg/s^2
boltzmannsConstant    = 1.3806504e-23      # J/K
massSolar             = 1.98892e30         # kg
parsec                = 3.08567758135e16   # m

# Galacticus' composition conventions (source/numerical/constants/astronomical.F90).
hydrogenByMassPrimordial = 0.7514
hydrogenByMassSolar      = 0.7070
metallicitySolar         = 0.0188

# The gravitational constant in Msun, pc, km/s units.
gravitationalConstantPc = gravitationalConstant*massSolar/parsec/1.0e6

def hydrogenMassFraction(metallicityRelativeToSolar):
    """Galacticus' hydrogen mass fraction at a given metallicity relative to Solar."""
    return min(max(metallicityRelativeToSolar*(hydrogenByMassSolar-hydrogenByMassPrimordial)+hydrogenByMassPrimordial,0.7),hydrogenByMassPrimordial)

def surfaceDensityExponential(mass,radiusScale,radius):
    """Surface density [Msun/pc^2] of an exponential disk of mass `mass` [Msun] and scale length
    `radiusScale` [pc] at radius `radius` [pc]."""
    return mass/(2.0*math.pi*radiusScale**2)*math.exp(-radius/radiusScale)

def pressureMidplane(surfaceDensityGas,surfaceDensityStellar,velocityDispersionGas,heightScaleStellar):
    """Midplane pressure, P_ext/k_B [K/cm^3], of a disk of locally isothermal gas and stars, for surface
    densities [Msun/pc^2], gas velocity dispersion [km/s], and stellar scale height [pc]."""
    velocityDispersionStellar=math.sqrt(math.pi*gravitationalConstantPc*heightScaleStellar*surfaceDensityStellar)
    pressure                 =0.5*math.pi*gravitationalConstantPc*surfaceDensityGas*(surfaceDensityGas+velocityDispersionGas/velocityDispersionStellar*surfaceDensityStellar)
    # Convert Msun (km/s)^2/pc^3 to K/cm^3.
    return pressure*massSolar*1.0e6/(parsec*1.0e2)**3/boltzmannsConstant

def molecularFractionBlitz2006(pressure,pressureCharacteristic=3.5e4,pressureExponent=0.92):
    """Molecular fraction, eqns. (11) and (21) of Blitz & Rosolowsky (2006), for a pressure P/k_B [K/cm^3]."""
    ratioMolecular=(pressure/pressureCharacteristic)**pressureExponent
    return ratioMolecular/(1.0+ratioMolecular)

def rateSurfaceDensityBlitz2006(surfaceDensityGas,surfaceDensityStellar,metallicityRelativeToSolar,             \
                                velocityDispersionGas=10.0,heightScaleStellar=None,                            \
                                frequencyNormalization=5.25e-10,surfaceDensityCritical=200.0,exponent=0.4,      \
                                pressureCharacteristic=3.5e4,pressureExponent=0.92):
    """Star formation rate surface density [Msun/Gyr/Mpc^2] for the Blitz & Rosolowsky (2006) law."""
    pressure             =pressureMidplane        (surfaceDensityGas,surfaceDensityStellar,velocityDispersionGas,heightScaleStellar)
    fractionMolecular    =molecularFractionBlitz2006(pressure,pressureCharacteristic,pressureExponent)
    surfaceDensityHydrogen=hydrogenMassFraction(metallicityRelativeToSolar)*surfaceDensityGas
    frequency            =frequencyNormalization*(1.0+(surfaceDensityHydrogen/surfaceDensityCritical)**exponent)
    # Convert Msun/pc^2/yr to Msun/Gyr/Mpc^2.
    return frequency*fractionMolecular*surfaceDensityHydrogen*1.0e21

def molecularFractionKrumholz2009(surfaceDensityGas,metallicityRelativeToSolar,clumpingFactor=5.0,fast=False):
    """Molecular fraction, eqn. (2) of Krumholz, McKee & Tumlinson (2009), for a total gas surface density
    [Msun/pc^2]. With `fast` set, the McKee & Krumholz (2010) approximation is used instead."""
    chi                     =0.77*(1.0+3.1*metallicityRelativeToSolar**0.365)
    surfaceDensityComplex   =clumpingFactor*surfaceDensityGas
    s                       =math.log(1.0+0.6*chi+0.01*chi**2)/(0.04*surfaceDensityComplex*metallicityRelativeToSolar)
    if fast:
        return 1.0-0.75*s/(1.0+0.25*s) if s < 2.0 else 0.0
    delta                   =0.0712*(0.1/s+0.675)**-2.8
    return 1.0-(1.0+(0.75*s/(1.0+delta))**-5)**-0.2

def rateSurfaceDensityKrumholz2009(surfaceDensityGas,metallicityRelativeToSolar,clumpingFactor=5.0,fast=False,  \
                                   frequencyStarFormation=0.385,surfaceDensityTransition=85.0):
    """Star formation rate surface density [Msun/Gyr/Mpc^2] for the Krumholz et al. (2009) law."""
    fractionMolecular=molecularFractionKrumholz2009(surfaceDensityGas,metallicityRelativeToSolar,clumpingFactor,fast)
    exponent         =+0.33 if surfaceDensityGas > surfaceDensityTransition else -0.33
    # Convert Msun/pc^2/Gyr to Msun/Gyr/Mpc^2.
    return frequencyStarFormation*fractionMolecular*surfaceDensityGas*(surfaceDensityGas/surfaceDensityTransition)**exponent*1.0e12

# Self-checks of this script, independent of anything above.
#  * The molecular fraction must equal one half where the pressure equals the characteristic pressure.
assert abs(molecularFractionBlitz2006(3.5e4)-0.5) < 1.0e-14
#  * The Krumholz et al. (2009) molecular fraction must vanish as the surface density does, and approach unity
#    at high surface density.
assert molecularFractionKrumholz2009(1.0e-3,1.0) < 1.0e-6
assert molecularFractionKrumholz2009(1.0e+4,1.0) > 1.0-1.0e-3
#  * Where the gas surface density equals the transition surface density the rate is simply nu f Sigma_gas.
assert abs(rateSurfaceDensityKrumholz2009(85.0,1.0)-0.385*molecularFractionKrumholz2009(85.0,1.0)*85.0*1.0e12) < 1.0e-6

if __name__ == "__main__":
    # The disk of the unit test: a Milky Way-like exponential disk at Solar metallicity.
    massGas                   = 1.0e10  # Msun
    massStellar               = 5.0e10  # Msun
    radiusScale               = 3.0e03  # pc
    metallicityRelativeToSolar= 1.0
    velocityDispersionGas     =10.0     # km/s
    heightToRadialScaleDisk   = 0.137
    heightScaleStellar        =heightToRadialScaleDisk*radiusScale
    print(f"Hydrogen mass fraction at Z/Z_sun = {metallicityRelativeToSolar}: {hydrogenMassFraction(metallicityRelativeToSolar):.10f}")
    print(f"Central gas     surface density: {surfaceDensityExponential(massGas    ,radiusScale,0.0):.10f} Msun/pc^2")
    print(f"Central stellar surface density: {surfaceDensityExponential(massStellar,radiusScale,0.0):.10f} Msun/pc^2")
    print()
    print("Blitz & Rosolowsky (2006):")
    print(f"{'R/R_d':>7s} {'Sigma_gas':>14s} {'P/k_B':>14s} {'R_mol':>14s} {'f_H2':>14s} {'SigmaDot_star':>18s}")
    for radiusRelative in (0.5,1.0,2.0,3.0,4.0,6.0):
        radius               =radiusRelative*radiusScale
        surfaceDensityGas_   =surfaceDensityExponential(massGas    ,radiusScale,radius)
        surfaceDensityStellar=surfaceDensityExponential(massStellar,radiusScale,radius)
        pressure             =pressureMidplane(surfaceDensityGas_,surfaceDensityStellar,velocityDispersionGas,heightScaleStellar)
        ratioMolecular       =(pressure/3.5e4)**0.92
        print(f"{radiusRelative:7.2f} {surfaceDensityGas_:20.13e} {pressure:20.13e} {ratioMolecular:20.13e} {molecularFractionBlitz2006(pressure):20.13e} {rateSurfaceDensityBlitz2006(surfaceDensityGas_,surfaceDensityStellar,metallicityRelativeToSolar,velocityDispersionGas,heightScaleStellar):20.13e}")
    print()
    # The radius at which the gas surface density equals the Krumholz et al. (2009) transition surface density.
    radiusTransitionRelative=math.log(surfaceDensityExponential(massGas,radiusScale,0.0)/85.0)
    print(f"Sigma_gas = 85 Msun/pc^2 at R = {radiusTransitionRelative:.16f} R_d")
    print()
    print("Krumholz, McKee & Tumlinson (2009):")
    print(f"{'R/R_d':>7s} {'Sigma_gas':>14s} {'s':>14s} {'f_H2':>14s} {'SigmaDot_star':>18s} {'f_H2 (fast)':>14s}")
    for radiusRelative in (0.5,radiusTransitionRelative,1.0,2.0,3.0):
        radius            =radiusRelative*radiusScale
        surfaceDensityGas_=surfaceDensityExponential(massGas,radiusScale,radius)
        chi               =0.77*(1.0+3.1*metallicityRelativeToSolar**0.365)
        s                 =math.log(1.0+0.6*chi+0.01*chi**2)/(0.04*5.0*surfaceDensityGas_*metallicityRelativeToSolar)
        print(f"{radiusRelative:12.9f} {surfaceDensityGas_:20.13e} {s:20.13e} {molecularFractionKrumholz2009(surfaceDensityGas_,metallicityRelativeToSolar):20.13e} {rateSurfaceDensityKrumholz2009(surfaceDensityGas_,metallicityRelativeToSolar):20.13e} {molecularFractionKrumholz2009(surfaceDensityGas_,metallicityRelativeToSolar,fast=True):20.13e}")
    print()
    # The limiting cases tested by the unit test, in each of which the disk is compressed so that the gas becomes fully
    # molecular. Each is evaluated at one half of the scale length of the compressed disk.
    print("Fully molecular limits:")
    for factorCompression in (10.0,20.0):
        radiusScaleCompressed=radiusScale/factorCompression
        surfaceDensityGas_   =surfaceDensityExponential(massGas    ,radiusScaleCompressed,0.5*radiusScaleCompressed)
        surfaceDensityStellar=surfaceDensityExponential(massStellar,radiusScaleCompressed,0.5*radiusScaleCompressed)
        pressure             =pressureMidplane(surfaceDensityGas_,surfaceDensityStellar,velocityDispersionGas,heightToRadialScaleDisk*radiusScaleCompressed)
        print(f"  R_d/{factorCompression:4.1f}: Sigma_gas = {surfaceDensityGas_:20.13e} Msun/pc^2"                                        \
              f"  1-f_H2 (Blitz & Rosolowsky) = {1.0-molecularFractionBlitz2006(pressure):12.5e}"                                         \
              f"  1-f_H2 (Krumholz et al.) = {1.0-molecularFractionKrumholz2009(surfaceDensityGas_,metallicityRelativeToSolar):12.5e}"    \
              f"  SigmaDot_star (Krumholz et al.) = {rateSurfaceDensityKrumholz2009(surfaceDensityGas_,metallicityRelativeToSolar):20.13e}")
