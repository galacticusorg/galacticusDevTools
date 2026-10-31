#!/usr/bin/env python3
# Independent reference values for the H-H2 cooling function of Galli & Palla (1998), as implemented in
# Galacticus by coolingFunctionMolecularHydrogenGalliPalla
# (source/cooling/cooling_function/molecular_hydrogen_Galli_Palla.F90), for use by the unit test
# source/tests/cooling_function_molecular_hydrogen_Galli_Palla.F90.
#
# Nothing here is taken from the Galacticus implementation - every expression is written directly from the
# papers:
#
#  * Galli & Palla (1998; A&A, 335, 403), appendix, write the H-H2 cooling function (in erg cm^3 s^-1, per
#    unit n(H) n(H2)) in the form of Hollenbach & McKee (1979),
#
#        Lambda[n(H),T] = Lambda(LTE) / (1 + n_cr/n(H)),   n_cr/n(H) = Lambda(LTE) / Lambda[n(H) -> 0],
#
#    where n(H) is the number density of *atomic* hydrogen (the collision partner of H2), and fit the
#    low-density limit as
#
#        log10 Lambda[n(H) -> 0] = -103.0 + 97.59 x - 48.05 x^2 + 10.80 x^3 - 0.9032 x^4,  x = log10(T/K).
#
#    The cooling rate per unit volume is then n(H) n(H2) Lambda[n(H),T], which tends to n(H2) L(LTE) (the LTE
#    emission per molecule) at high density, independent of n(H).
#
#  * Hollenbach & McKee (1979; ApJS, 41, 555), eqns. (6.37) and (6.38), give the LTE rotational and
#    vibrational cooling per H2 molecule (erg s^-1), with T3 = T/1000 K,
#
#        L_r = 9.5e-22 T3^3.76 / (1 + 0.12 T3^2.1) exp[-(0.13/T3)^3] + 3.0e-24 exp(-0.51/T3),
#        L_v = 6.7e-19 exp(-5.86/T3) + 1.6e-18 exp(-11.7/T3),
#
#    so that Lambda(LTE) = (L_r + L_v)/n(H).
#
# The logarithmic gradients of the cooling rate per unit volume with respect to density (at fixed
# composition, i.e. all species densities proportional to the hydrogen density) and temperature are computed
# by central finite differences.

import math

def coolingLowDensityLimit(temperature):
    """Low-density limit of the H-H2 cooling function [erg cm^3 s^-1] (Galli & Palla 1998)."""
    x=math.log10(temperature)
    return 10.0**(-103.0+97.59*x-48.05*x**2+10.80*x**3-0.9032*x**4)

def coolingPerMoleculeLTE(temperature):
    """LTE rotational plus vibrational cooling per H2 molecule [erg s^-1] (Hollenbach & McKee 1979)."""
    t3        =temperature/1.0e3
    rotational=9.5e-22*t3**3.76/(1.0+0.12*t3**2.1)*math.exp(-(0.13/t3)**3)+3.0e-24*math.exp(-0.51/t3)
    vibrational=6.7e-19*math.exp(-5.86/t3)+1.6e-18*math.exp(-11.7/t3)
    return rotational+vibrational

def coolingRate(numberDensityAtomicHydrogen,numberDensityMolecularHydrogen,temperature):
    """H-H2 cooling rate per unit volume [erg cm^-3 s^-1]."""
    coolingLTE         =coolingPerMoleculeLTE(temperature)/numberDensityAtomicHydrogen
    ratioDensityCritical=coolingLTE/coolingLowDensityLimit(temperature)
    return numberDensityAtomicHydrogen*numberDensityMolecularHydrogen*coolingLTE/(1.0+ratioDensityCritical)

# Composition of the test gas, as fractions of the hydrogen density: half atomic, so that normalizing by the total
# hydrogen density rather than the atomic would be a factor of two in the LTE limit.
fractionAtomic   =0.5
fractionMolecular=1.0e-3

def coolingRateComposition(numberDensityHydrogen,temperature):
    return coolingRate(fractionAtomic*numberDensityHydrogen,fractionMolecular*numberDensityHydrogen,temperature)

def logSlope(function,x,step=1.0e-4):
    return (math.log(function(x*math.exp(+step)))-math.log(function(x*math.exp(-step))))/(2.0*step)

if __name__ == "__main__":
    # Self-checks of the limits.
    for temperature in (1.0e2,1.0e3):
        # Low density: Lambda -> n(H) n(H2) Lambda[n -> 0].
        low=coolingRate(1.0e-6,1.0e-9,temperature)/(1.0e-6*1.0e-9*coolingLowDensityLimit(temperature))
        assert abs(low-1.0) < 1.0e-6, low
        # High density: Lambda -> n(H2) L(LTE), independent of n(H).
        high=coolingRate(1.0e12,1.0e9,temperature)/(1.0e9*coolingPerMoleculeLTE(temperature))
        assert abs(high-1.0) < 1.0e-6, high
    numberDensities=(1.0e0,1.0e4,1.0e10)
    temperatures   =(3.0e2,1.0e3,3.0e3)
    print(f"Composition: n(H)/n_H = {fractionAtomic}, n(H2)/n_H = {fractionMolecular}")
    print(f"{'n_H':>8s} {'T':>8s} {'Lambda [erg/cm^3/s]':>22s} {'dlnL/dln n':>20s} {'dlnL/dln T':>20s}")
    values=[]
    for numberDensity in numberDensities:
        for temperature in temperatures:
            rate         =coolingRateComposition(numberDensity,temperature)
            slopeDensity =logSlope(lambda n: coolingRateComposition(n,temperature),numberDensity)
            slopeTemperature=logSlope(lambda t: coolingRateComposition(numberDensity,t),temperature)
            values.append((numberDensity,temperature,rate,slopeDensity,slopeTemperature))
            print(f"{numberDensity:8.1e} {temperature:8.1e} {rate:22.13e} {slopeDensity:20.13e} {slopeTemperature:20.13e}")
    print()
    print("Fortran initializers (loop order: density outer, temperature inner):")
    def fortran(name,column):
        print(f"{name}=["+",".join(f"{v[column]:.13e}".replace("e","d") for v in values)+"]")
    fortran("coolingReference"            ,2)
    fortran("slopeDensityReference"       ,3)
    fortran("slopeTemperatureReference"   ,4)
