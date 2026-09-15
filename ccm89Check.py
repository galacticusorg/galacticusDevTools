# Compare the Galacticus Cardelli et al. (1989) transcription against the independent dust_extinction implementation.
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
