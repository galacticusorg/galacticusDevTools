#!/usr/bin/env python3
# Variants of the Benson & Babul (2009) model using the alpha(j) fits adopted in Galacticus' accretionDisksADAF (exponential field
# enhancement): alpha=0.010 for E_ADAF=1, alpha=0.015+0.02j^4 for E_ADAF=E_ISCO. Also evaluates jet efficiencies at the spins used
# in source/tests/accretion_disks.F90 to cross-check this independent implementation against Galacticus.
import numpy as np
from bensonBabul2009 import ADAF, equilibrium, radiusISCO

class ADAFGalacticus(ADAF):
    def alpha(self,j):
        return 0.010 if self.energy == "pureADAF" else 0.015+0.02*j**4

spins       = np.array([0.000,0.200,0.400,0.600,0.800,0.950])
expected    = np.array([2.993e-3,3.916e-3,6.571e-3,1.564e-2,5.246e-2,4.119e-1])
for metricA in ("paper","kerr"):
    for radiusL in ("horizon","ISCO"):
        print(f"\nA={metricA:5s} L@{radiusL}  [Galacticus alpha(j)]")
        for energy in ("pureADAF","ISCO"):
            m  = ADAFGalacticus(energy=energy,metricA=metricA,radiusL=radiusL)
            jN = equilibrium(m.spinUpNoJet)
            jJ = equilibrium(m.spinUp)
            print(f"  E={energy:8s} j_eq(noJet)={np.round(jN,3)} j_eq(jet)={np.round(jJ,3)} eta(j_eq)={np.round([m.powerJetDisk(j)+m.powerJetBH(j) for j in jJ],3)}")
    # Jet efficiency as in the Galacticus unit test (pure ADAF, exponential enhancement, gamma=1.444, cap at 2).
    m   = ADAFGalacticus(energy="pureADAF",metricA=metricA)
    eff = np.array([min(m.powerJetDisk(j)+(m.powerJetBH(j) if j > 5.0e-8 else 0.0),2.0) for j in spins])
    print(f"  jet efficiency vs spin: {np.array2string(eff,precision=4)}")
    print(f"  ratio to Galacticus test values: {np.array2string(eff/expected,precision=4)}")
