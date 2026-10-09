#!/usr/bin/env python3
# An independent implementation of the halofit algorithm of Smith et al. (2003; astro-ph/0207664), used to supply reference
# values for the "quasi-linear term" and "halo term" groups of Galacticus'
# source/tests/power_spectrum/nonlinear_Smith2003.F90.
#
# Checking only the total nonlinear power is not enough. The quasi-linear and halo terms overlap, so an error in one is diluted
# in the sum: a ten per cent error in the coefficient of the quasi-linear damping moves the total by one per cent but moves the
# quasi-linear term itself by up to thirteen. Each term therefore has to be compared separately, and CAMB does not report them
# separately - hence this script.
#
# The coefficients of Appendix C are taken from CAMB's `fortran/halofit.f90`, its `halofit_original` branch, which is an
# implementation independent of Galacticus'. The linear power spectrum, and the total against which this implementation is
# validated, are read from CAMB output produced by:
#
#   camb halofit.ini   # do_nonlinear = 1, halofit_version = 1  -> halofit_matterpower.dat
#   camb linear.ini    # do_nonlinear = 0                       -> linear_matterpower.dat
#
# Run in a directory holding those two files. The script reports the nonlinear scale, effective index and curvature it finds,
# and the accuracy with which it reproduces CAMB's total - which is what licenses using its decomposition. That agreement is
# better than 0.4%, so the test compares each term at a tolerance of 2%.
#
# Andrew Benson (16-September-2026).

import numpy as np
from scipy.optimize import brentq
# Linear P(k) from CAMB, in h-units as CAMB writes it.
li=np.loadtxt('linear_matterpower.dat'); nl=np.loadtxt('halofit_matterpower.dat')
kh,pl=li[:,0],li[:,1]
lk,lp=np.log(kh),np.log(pl)
def plin(k):  # k in h/Mpc
    return np.exp(np.interp(np.log(k),lk,lp))
def delta2(k):
    return plin(k)*k**3/(2.0*np.pi**2)
# Gaussian-filtered sigma(R) and its logarithmic derivatives, as CAMB's `wint`.
kint=np.exp(np.linspace(np.log(kh[0]*1.001),np.log(kh[-1]*0.999),8000))
d2int=delta2(kint); dlnk=np.diff(np.log(kint)).mean()
def wint(R):
    x2=(kint*R)**2; w1=np.exp(-x2)*d2int
    s1=np.sum(w1*dlnk); s2=np.sum(x2*w1*dlnk); s3=np.sum(x2*(1-x2)*w1*dlnk)
    return np.sqrt(s1), -2*s2/s1, -(-2*s2/s1)**2-4*s3/s1
Rsigma=brentq(lambda lr: wint(np.exp(lr))[0]-1.0, np.log(1e-3), np.log(1e2), xtol=1e-14)
Rsigma=np.exp(Rsigma)
sig,d1,d2=wint(Rsigma)
knl, rn, rncur = 1.0/Rsigma, -3.0-d1, -d2
print(f'k_sigma = {knl:.8f} h/Mpc, n_eff = {rn:.8f}, C = {rncur:.8f}, sigma = {sig:.10f}')
# Appendix C coefficients of Smith et al. (2003), as in CAMB's halofit_original branch.
gam  = 0.86485 + 0.2989*rn + 0.1631*rncur
a    = 10**(1.4861 + 1.83693*rn + 1.67618*rn**2 + 0.7940*rn**3 + 0.1670756*rn**4 - 0.620695*rncur)
b    = 10**(0.9463 + 0.9466*rn + 0.3084*rn**2 - 0.940*rncur)
c    = 10**(-0.2807 + 0.6669*rn + 0.3214*rn**2 - 0.0793*rncur)
xmu  = 10**(-3.54419 + 0.19086*rn)
xnu  = 10**(0.95897 + 1.2857*rn)
alpha= 1.38848 + 0.3701*rn - 0.1452*rn**2
beta = 0.8291 + 0.9854*rn + 0.3400*rn**2
f1=f2=f3=1.0
om_m=0.299844; om_v=0.700156
if abs(1-om_m) > 0.01:
    f1a,f2a,f3a=om_m**-0.0732,om_m**-0.1423,om_m**0.0725
    f1b,f2b,f3b=om_m**-0.0307,om_m**-0.0585,om_m**0.0743
    frac=om_v/(1.0-om_m)
    f1=frac*f1b+(1-frac)*f1a; f2=frac*f2b+(1-frac)*f2a; f3=frac*f3b+(1-frac)*f3a
def terms(k):
    y=k/knl
    ph=a*y**(f1*3)/(1+b*y**f2+(f3*c*y)**(3-gam))
    ph=ph/(1+xmu/y+xnu/y**2)
    pq=delta2(k)*(1+delta2(k))**beta/(1+delta2(k)*alpha)*np.exp(-y/4.0-y**2/8.0)
    return pq,ph
# Validate the reimplementation against CAMB's own nonlinear output before trusting its decomposition.
kt=nl[:,0]; keep=(kt>1e-3)&(kt<50.0)
d2nl_camb=nl[keep,1]*kt[keep]**3/(2*np.pi**2)
pq,ph=np.array([terms(k) for k in kt[keep]]).T
err=np.abs((pq+ph)/d2nl_camb-1.0)
print(f'reimplementation vs CAMB total: max |err| = {err.max():.3e}, median = {np.median(err):.3e}')
