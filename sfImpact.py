import math
# Blitz & Rosolowsky (2006): molecular fraction in an MW-like exponential disk, using Galacticus' pressure
# P = (pi/2) G Sigma_g^2 [1 + sigma_g/Sigma_g sqrt(Sigma_*/(pi G h_*))], with P0/k = 4.54 (as coded) and 3.5e4 (paper).
G   = 4.30091e-3        # pc (km/s)^2 / Msun
k   = 1.380649e-23; Msun=1.98892e30; pc_cm=3.08567758e18
toK = Msun*1e6/pc_cm**3/k   # Msun (km/s)^2 / pc^3 -> K cm^-3
Mg, Ms, Rd, sg, hr = 1.0e10, 5.0e10, 3.0e3, 10.0, 0.137
for x in (0.5,1.0,2.0,3.0,4.0,6.0):
    R  = x*Rd
    Sg = Mg/(2*math.pi*Rd**2)*math.exp(-x); Ss = Ms/(2*math.pi*Rd**2)*math.exp(-x)
    P  = 0.5*math.pi*G*Sg**2*(1+sg/Sg*math.sqrt(Ss/(math.pi*G*hr*Rd)))*toK
    out=[]
    for P0 in (4.54,3.5e4):
        Rm=(P/P0)**0.92
        out.append((min(Rm,1.0),Rm/(1+Rm)))
    print(f"R={x:3.1f}R_d  Sigma_g={Sg:6.2f} Msun/pc2  P/k={P:9.3e}  f(code,P0=4.54)={out[0][0]:.3f}  f(code,P0=3.5e4)={out[1][0]:.3f}  f(paper R/(1+R),3.5e4)={out[1][1]:.3f}")
# KMT09: effect of the X_H factor on f_H2 (slow fit) at Z'=1, c=5.
def fH2(Scomp,Z=1.0):
    chi=0.77*(1+3.1*Z**0.365); s=math.log(1+0.6*chi+0.01*chi**2)/(0.04*Scomp*Z)
    d=0.0712*(0.1/s+0.675)**-2.8
    return 1-(1+(0.75*s/(1+d))**-5)**-0.2
X=0.7070
print()
for Sg in (1,2,3,5,10,20):
    print(f"Sigma_g={Sg:3d}: f_H2(paper, c*Sigma_g)={fH2(5*Sg):.3f}  f_H2(code, c*X_H*Sigma_g)={fH2(5*X*Sg):.3f}")
