#!/usr/bin/env python3
# Independent implementation of the Benson & Babul (2009; MNRAS 397, 1302; arXiv:0905.2378) ADAF + jet model, written from the
# equations in the paper (not from the Galacticus source). Used to test whether the published results (equilibrium spins, jet
# efficiencies, black hole fraction of jet power) are reproduced, and to discriminate between variants of the model:
#   metricA   : "paper" uses eqn. (A15) as printed, A = 1 + j/r^2 + 2j^2/r^3; "kerr" uses the standard Kerr metric factor
#               A = 1 + j^2/r^2 + 2j^2/r^3.
#   radiusL   : radius at which L_ADAF is evaluated in the spin-up function (eqn. 7): "horizon" (as stated in the text) or "ISCO".
import numpy as np
from scipy.optimize import brentq

def radiusISCO(j):
    A1 = 1.0+(1.0-j**2)**(1.0/3.0)*((1.0+j)**(1.0/3.0)+(1.0-j)**(1.0/3.0))
    A2 = np.sqrt(3.0*j**2+A1**2)
    return 3.0+A2-np.sqrt((3.0-A1)*(3.0+A1+2.0*A2))

def energyISCO(j):
    r = radiusISCO(j)
    return (r**2-2.0*r+j*np.sqrt(r))/r/np.sqrt(r**2-3.0*r+2.0*j*np.sqrt(r))

def radiusHorizon(j):
    return 1.0+np.sqrt(1.0-j**2)

class ADAF:
    def __init__(self,energy="pureADAF",metricA="paper",radiusL="horizon",gamma=1.444,alpha=None):
        self.energy  = energy
        self.metricA = metricA
        self.radiusL = radiusL
        self.gamma   = gamma
        self.alphaFixed = alpha
        # Thermal pressure fraction from eqn. (A1).
        self.beta    = (8.0-6.0*gamma)/3.0/(1.0-gamma)

    def alpha(self,j):
        if self.alphaFixed is not None:
            return self.alphaFixed
        # Eqn. (8).
        return 0.025+0.055*j**2 if self.energy == "pureADAF" else 0.025+0.4*j**4

    def D(self,j,r):
        return 1.0-2.0/r+(j/r)**2                                                  # (A14)

    def A(self,j,r):
        if self.metricA == "paper":
            return 1.0+j/r**2+2.0*j**2/r**3                                        # (A15) as printed
        else:
            return 1.0+j**2/r**2+2.0*j**2/r**3                                     # Kerr metric

    def omega(self,j,r):
        return 2.0*j/self.A(j,r)/r**3                                              # (A18)

    def V(self,j,r):
        rI  = radiusISCO(j)
        rh  = radiusHorizon(j)
        z   = r /rI
        zh  = rh/rI
        g   = self.gamma
        aE  = self.alpha(j)*(1.0+6.450*(g-1.444)+1.355*(g-1.444)**2)              # (A10)
        v1  = 9.0*np.log(9.0*z)                                                    # (A5)
        v2  = np.exp(-0.66*(1.0-2.0*aE)*np.log(aE/0.1)*np.log(z/zh))               # (A6)
        v3  = 1.0-np.exp(-z*(0.16*(j-1.0)+0.76))                                   # (A7)
        v4  = 1.4+0.29065*(j-0.5)**4-0.8756*(j-0.5)**2+(-0.33*j+0.45035)*(1.0-np.exp(-(z-zh))) # (A8)
        v5  = 2.3*np.exp(40.0*(j-1.0))*np.exp(-15.0*rI*(z-zh))+1.0                 # (A9)
        Psi = v1*v2*v3*v4*v5                                                       # (A4)
        rE  = rh+Psi*(r-rh)                                                        # (A3)
        return np.sqrt(1.0-(1.0-2.0/rE+(j/rE)**2))                                 # |V|, (A2)

    def Te(self,j,r):
        g  = self.gamma
        a  = self.alpha(j)
        rI = radiusISCO(j)
        t1 = -0.270278*g+1.36027                                                   # (A20)
        t2 = -0.94+4.4744*(g-1.444)-5.1402*(g-1.444)**2                            # (A21)
        t3 = 0.84*np.log10(a)+0.919-0.643*np.exp(-0.209/a)                         # (A22)
        t4 = (0.6365*rI-0.4828)*(1.0+11.9*np.exp(-0.838*rI**4))                    # (A23)
        t5 = 1.444*np.exp(-1.01*rI**0.86)+0.1                                      # (A24)
        return 0.31*(1.0+(t4/r)**0.9)**(t2+t3)/(r-t5)**t1                          # (A19)

    def eta(self,j,r):
        return 1.0+self.gamma/(self.gamma-1.0)*self.Te(j,r)                        # (A25)

    def L(self,j,r):
        g  = self.gamma
        la = np.log10(self.alpha(j))
        rI = radiusISCO(j)
        e1 = 0.0871*rI-0.10282                                                     # (A27)
        e2 = 0.5-7.7983*(g-1.333)**1.26                                            # (A28)
        e3 = 0.153*(rI-0.6)**0.30+0.105                                            # (A29)
        e4 = e3*(0.9*g-0.2996)*(1.202-0.08*(la+2.5)**2.6)                          # (A30)
        e5 = -1.8*g+4.299-0.018+0.018*(la+2.0)**3.571                              # (A31)
        e6 = e4*(((0.14*np.log10(r)**e5+0.23)/e4)**10+1.0)**0.1                    # (A32)
        etaL = e2+(e1+10.0**e6)*(1.15-0.03*(la+3.0)**2.37)                         # (A26)
        return etaL/self.eta(j,r)

    def gammaR(self,j,r):
        return np.sqrt(1.0/(1.0-self.V(j,r)**2))                                   # (A16)

    def gammaPhi(self,j,r):
        return np.sqrt(1.0+self.L(j,r)**2/r**2/self.A(j,r)/self.gammaR(j,r)**2)    # (A17)

    def H(self,j,r):
        A   = self.A(j,r)
        D   = self.D(j,r)
        w   = self.omega(j,r)
        L   = self.L(j,r)
        gR  = self.gammaR(j,r)
        gP  = self.gammaPhi(j,r)
        nuz2 = (j**2+(1.0-(j*w)**2)*L**2-((j*gP)**2/A)*(gR*np.sqrt(D))**2
                -gR*np.sqrt(D)*(2.0*L*w*gP*j**2)/np.sqrt(A))/r**4                  # (A13)
        return np.sqrt(self.Te(j,r)/self.eta(j,r)/r**2/nuz2)                       # (A12)

    def OmegaZAMO(self,j,r):
        return self.L(j,r)/r**2/self.gammaR(j,r)/self.gammaPhi(j,r)*np.sqrt(self.D(j,r)/self.A(j,r)**3) # (B3)

    def g(self,j,r):
        tau = min(1.0/self.OmegaZAMO(j,r),r*self.gammaPhi(j,r)/np.sqrt(self.D(j,r))/self.V(j,r))       # (B7)
        return np.exp(self.omega(j,r)*tau)

    def powerJet(self,j,r,Omega):
        # Common part of eqns. (13) and (14), in units of Mdot c^2.
        A    = self.A(j,r)
        D    = self.D(j,r)
        V    = self.V(j,r)
        gR   = self.gammaR(j,r)
        gP   = self.gammaPhi(j,r)
        betaP = np.sqrt(1.0-1.0/gP**2)
        return (3.0/80.0*(1.0-self.beta)*self.g(j,r)**2*r**2*gR**2*gP**2/A/V/self.H(j,r)
                *np.sqrt((1.0-V**2)/D)*self.Te(j,r)*Omega**2*(2.0*j*betaP/r**2+np.sqrt(D))**2)

    def powerJetDisk(self,j):
        r = radiusISCO(j)
        return self.powerJet(j,r,self.OmegaZAMO(j,r)+self.omega(j,r))               # (13)

    def powerJetBH(self,j):
        r = 2.0                                                                    # Static limit in the equatorial plane.
        return self.powerJet(j,r,self.omega(j,r))                                  # (14)

    def fractionBH(self,j):
        return 1.0-1.0/self.g(j,radiusISCO(j))**2

    def spinUpNoJet(self,j):
        r = radiusHorizon(j) if self.radiusL == "horizon" else radiusISCO(j)
        E = 1.0 if self.energy == "pureADAF" else energyISCO(j)
        return self.L(j,r)-2.0*j*E                                                  # (7)

    def spinUp(self,j):
        S = ((1.0+np.sqrt(1.0-j**2))**2+j**2)*np.sqrt(1.0-j**2)/j
        return self.spinUpNoJet(j)-S*(self.fractionBH(j)*self.powerJetDisk(j)+self.powerJetBH(j)) # (12)

def equilibrium(f,lo=0.5,hi=0.9999):
    js = np.linspace(lo,hi,2000)
    s  = np.array([f(j) for j in js])
    i  = np.where(np.sign(s[:-1]) != np.sign(s[1:]))[0]
    return [brentq(f,js[k],js[k+1]) for k in i]

if __name__ == "__main__":
    print("Published (Benson & Babul 2009): no jet j_eq=0.97 (E=1), 0.96 (E=E_ISCO); with jet j_eq=0.93 (E=1), 0.92 (E=E_ISCO);")
    print("                                 eta(j_eq)=0.16 (E=1), 0.06 (E=E_ISCO); f_BH(disk)=72.8% [total 93%] at j=0.8, 92.9% [96.6%] at j=0.9")
    for metricA in ("paper","kerr"):
        for radiusL in ("horizon","ISCO"):
            print(f"\nA={metricA:5s} L@{radiusL}")
            for energy in ("pureADAF","ISCO"):
                m   = ADAF(energy=energy,metricA=metricA,radiusL=radiusL)
                jN  = equilibrium(m.spinUpNoJet)
                jJ  = equilibrium(m.spinUp)
                etaEq = [m.powerJetDisk(j)+m.powerJetBH(j) for j in jJ]
                fr  = []
                for j in (0.8,0.9):
                    pD, pB = m.powerJetDisk(j), m.powerJetBH(j)
                    fr.append((m.fractionBH(j),(m.fractionBH(j)*pD+pB)/(pD+pB)))
                print(f"  E={energy:8s} j_eq(noJet)={np.round(jN,3)} j_eq(jet)={np.round(jJ,3)} eta(j_eq)={np.round(etaEq,3)} "
                      f"f_BH(0.8)={fr[0][0]:.3f} [{fr[0][1]:.3f}] f_BH(0.9)={fr[1][0]:.3f} [{fr[1][1]:.3f}]")
