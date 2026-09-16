#!/usr/bin/env python3
# Compare the Galacticus Cardelli et al. (1989) transcription against the independent dust_extinction implementation, and
# emit reference values for the unit test.
#
# Run with no arguments it reports the worst relative disagreement over the fitted range for three values of R_V. Run with
# `--reference` it instead prints the values of A(lambda)/A(V) which `dust_extinction` gives at the wavelengths used by the
# "Cardelli et al. (1989) against an independent implementation" group of Galacticus'
# source/tests/dust/extinction_curves.F90, in a form which can be pasted into that file.
#
# Those wavelengths are round numbers chosen so that the inverse wavelength each implementation forms lands unambiguously
# inside one of the four segments of the fit, away from the boundaries at x = 1.1, 3.3 and 5.9 inverse microns, where the
# segments are not continuous and a difference of one ulp would select a different branch in the two codes.
#
# Requires `numpy`, `astropy` and `dust_extinction`; the last is not part of astropy core.
#
# Andrew Benson (15-September-2026).
import sys
import numpy as np, astropy.units as u
from dust_extinction.parameter_averages import CCM89
def a_b(x):
    if 0.3<=x<1.1: return 0.574*x**1.61, -0.527*x**1.61
    if 1.1<=x<3.3:
        y=x-1.82
        a=1+0.17699*y-0.50447*y**2-0.02427*y**3+0.72085*y**4+0.01979*y**5-0.77530*y**6+0.32999*y**7
        b=1.41338*y+2.28305*y**2+1.07233*y**3-5.38434*y**4-0.62251*y**5+5.30260*y**6-2.09002*y**7
        return a,b
    if 3.3<=x<8.0:
        Fa,Fb=(0.0,0.0) if x<5.9 else (-0.04473*(x-5.9)**2-0.009779*(x-5.9)**3, 0.2130*(x-5.9)**2+0.1207*(x-5.9)**3)
        return 1.752-0.316*x-0.104/((x-4.67)**2+0.341)+Fa, -3.090+1.825*x+1.206/((x-4.62)**2+0.263)+Fb
    return 0.0,0.0
worst=0
for Rv in (2.5,3.1,5.0):
    m=CCM89(Rv=Rv)
    x=np.linspace(0.3,7.999,2000)
    ref=m(x/u.micron)
    gal=np.array([a+b/Rv for a,b in map(a_b,x)])
    d=np.max(np.abs(gal/ref-1)); worst=max(worst,d)
    print(f"Rv={Rv}: max |Galacticus/dust_extinction - 1| over 0.3<=x<8 = {d:.2e}")

# Reference values for the Galacticus unit test.
if "--reference" in sys.argv:
    wavelengths=[25000.0,12500.0,9500.0,6000.0,5494.5054945055,4000.0,3200.0,2900.0,2600.0,2200.0,2000.0,1750.0,1600.0,1450.0,1300.0]
    x          =np.array([1.0e4/w for w in wavelengths])
    for boundary in (0.3,1.1,3.3,5.9,8.0):
        assert np.all(np.abs(x-boundary) > 1.0e-6), f"a sample sits on the segment boundary at x={boundary}"
    print()
    for Rv,name in ((2.5,"RvLow"),(3.1,"RvStandard"),(5.0,"RvHigh")):
        values=CCM89(Rv=Rv)(x/u.micron)
        print(f"  referenceCardelli{name}:")
        for i in range(0,len(wavelengths),4):
            print("       & "+", ".join(f"{v:.13e}".replace("e","d") for v in values[i:i+4])+(", &" if i+4 < len(wavelengths) else "  &"))
