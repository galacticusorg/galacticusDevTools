# Independent check of the constants hard-coded in virialOrbitBenson2005 against the fitting function as coded.
import numpy as np
from scipy import integrate, optimize
a=[0.390052e+01,0.247973e+01,0.102373e+02,0.683922e+00,0.353953e+00,0.107716e+01,0.509837e+00,0.206204e+00,0.314641e+00]
def f(vr,vt):
    b1=a[2]*np.exp(-a[3]*(vt-a[4])**2)
    b2=a[5]*np.exp(-a[6]*(vt-a[7])**2)
    return a[0]*vt*np.exp(-a[1]*(vt-a[8])**2)*np.exp(-b1*(vr-b2)**2)
vMax=3.0
# Peak of f on [0,3]^2 (the rejection-sampling envelope pMax).
g=np.linspace(0,vMax,1201); VR,VT=np.meshgrid(g,g,indexing='ij'); F=f(VR,VT); i=np.unravel_index(F.argmax(),F.shape)
res=optimize.minimize(lambda x:-f(x[0],x[1]),[VR[i],VT[i]],method='Nelder-Mead',options={'xatol':1e-12,'fatol':1e-14})
print(f"peak f = {-res.fun:.6f} at (v_r,v_t)=({res.x[0]:.5f},{res.x[1]:.5f})   code pMax = 1.96797")
opts=dict(epsabs=0,epsrel=1e-11)
norm =integrate.dblquad(lambda vr,vt: f(vr,vt)             ,0,vMax,0,vMax,**opts)[0]
mvt  =integrate.dblquad(lambda vr,vt: vt*f(vr,vt)          ,0,vMax,0,vMax,**opts)[0]
mv2  =integrate.dblquad(lambda vr,vt: (vr**2+vt**2)*f(vr,vt),0,vMax,0,vMax,**opts)[0]
print(f"integral of f over [0,3]^2 = {norm:.6f}")
print(f"<v_t>      = {mvt/norm:.6f}   code 0.749265")
print(f"<v^2>^1/2  = {np.sqrt(mv2/norm):.6f}   code 1.254476")
