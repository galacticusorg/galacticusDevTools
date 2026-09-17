#!/usr/bin/env python3
"""Independent reference values for Galacticus' primordial hydrogen chemistry network.

Written from the published fits for the Tier 3 derivation checks of
`source/chemical/reaction_rates/hydrogen.F90`, which had no test.

Rate coefficients, from Abel et al. (1997; arXiv:astro-ph/9608040), their reaction numbers:

  k7   H  + e- -> H- + photon        (T in K,  two branches at 6000 K)
  k8   H- + H  -> H2 + e-            (T in eV, constant below 0.1 eV)
  k14  H- + e- -> H  + 2e-           (T in eV)
  k16  H- + H+ -> 2H                 (T in K)

Photo cross-sections, also from Abel et al. (1997):

  sigma24  H2  + photon -> H2+ + e-   (O'Neil & Reinhardt 1978)
  sigma26  H2+ + photon -> 2H+ + e-   (Shapiro & Kang 1987)
  sigma28  H2  + photon -> 2H         (Lyman and Werner bands, para and ortho)

The cross-sections are returned by Galacticus through an interpolating table built on a fixed
grid, so the references here are interpolated on that same grid: the comparison then tests the
fitting formulae, which are the physics, and not the tabulation, which is a numerical detail
shared by both. `--self-check` reports how much the tabulation itself costs.

Not covered here: H2+ + photon -> H + H+, which Galacticus takes from Shapiro & Kang (1987) while
Abel et al. use a different fit to Stancil (1994), so it cannot be checked against Abel; and
H + photon -> H+ + e-, which Galacticus delegates to its own photoionization cross-section class
rather than fitting here.

Usage:  ./hydrogenNetworkCheck.py [--self-check] [--fortran]
"""
import argparse
import math

# --- rate coefficients (Abel et al. 1997) ------------------------------------------------------

def k7(temperature):
    """H + e- -> H- + photon; temperature in K."""
    if temperature <= 1.0:
        return 1.429e-18
    logarithm = math.log10(temperature)
    if temperature <= 6000.0:
        return 1.429e-18*temperature**0.7620*temperature**(0.1523*logarithm)*temperature**(-3.274e-2*logarithm**2)
    return 3.802e-17*temperature**(0.1998*logarithm)*10.0**(4.0415e-5*logarithm**6-5.447e-3*logarithm**4)

def k8(temperatureElectronVolts):
    """H- + H -> H2 + e-; temperature in eV."""
    if temperatureElectronVolts < 0.1:
        return 1.428e-9
    L = math.log(temperatureElectronVolts)
    coefficients = [-20.06913897, 0.22898, 3.5998377e-2, -4.55512e-3, -3.10511544e-4,
                    1.0732940e-4, -8.36671960e-6, 2.23830623e-7]
    return math.exp(sum(c*L**n for n, c in enumerate(coefficients)))

def k14(temperatureElectronVolts):
    """H- + e- -> H + 2e-; temperature in eV."""
    L = math.log(temperatureElectronVolts)
    coefficients = [-18.01849334, 2.3608522, -0.28274430, 1.62331664e-2, -3.36501203e-2,
                    1.17832978e-2, -1.65619470e-3, 1.06827520e-4, -2.63128581e-6]
    return math.exp(sum(c*L**n for n, c in enumerate(coefficients)))

def k16(temperature):
    """H- + H+ -> 2H; temperature in K."""
    return 7.0e-8/math.sqrt(temperature/100.0)

# --- photo cross-sections (Abel et al. 1997) ---------------------------------------------------

def sigma24(energy):
    """H2 + photon -> H2+ + e-; energy in eV, cross-section in cm^2."""
    if   energy < 15.42: return 0.0
    elif energy < 16.50: return 6.2e-18*energy-9.40e-17
    elif energy < 17.70: return 1.4e-18*energy-1.48e-17
    return 2.5e-14/energy**2.71

def sigma26(energy):
    """H2+ + photon -> 2H+ + e-; energy in eV."""
    if 30.0 <= energy <= 90.0:
        return 10.0**(-16.926-4.528e-2*energy+2.238e-4*energy**2+4.245e-7*energy**3)
    return 0.0

def sigma28(energy, ratioOrthoToPara=0.0):
    """H2 + photon -> 2H, Lyman and Werner bands; energy in eV."""
    lymanPara = wernerPara = lymanOrtho = wernerOrtho = 0.0
    if   14.675 < energy <= 16.820: lymanPara =10.0**(-18.0+15.1289-1.05139*energy)
    elif 16.820 < energy <= 17.600: lymanPara =10.0**(-18.0-31.4100+1.8042e-2*energy**3-4.2339e-5*energy**5)
    if   14.675 < energy <= 17.700: wernerPara=10.0**(-18.0+13.5311-0.9182618*energy)
    if ratioOrthoToPara > 0.0:
        if   14.159 < energy <= 15.302: lymanOrtho =10.0**(-18.0+12.0218406-0.819429 *energy)
        elif 15.302 < energy <= 17.200: lymanOrtho =10.0**(-18.0+16.0464400-1.082438 *energy)
        if   14.159 < energy <= 17.200: wernerOrtho=10.0**(-18.0+12.8736700-0.85088597*energy)
    weightPara = 1.0/(ratioOrthoToPara+1.0)
    return weightPara*(lymanPara+wernerPara)+(1.0-weightPara)*(lymanOrtho+wernerOrtho)

# --- the tabulation Galacticus interpolates through --------------------------------------------

def tabulate(function, minimum, maximum, count, logarithmic):
    if logarithmic:
        nodes = [minimum*(maximum/minimum)**(i/(count-1)) for i in range(count)]
    else:
        nodes = [minimum+(maximum-minimum)*i/(count-1)     for i in range(count)]
    return nodes, [function(x) for x in nodes]

def interpolate(nodes, values, x, logarithmic):
    if x <= nodes[0] or x >= nodes[-1]:
        return 0.0                                  # extrapolationTypeZero at both ends
    for i in range(len(nodes)-1):
        if nodes[i] <= x <= nodes[i+1]:
            if logarithmic:
                f = (math.log(x)-math.log(nodes[i]))/(math.log(nodes[i+1])-math.log(nodes[i]))
            else:
                f = (x-nodes[i])/(nodes[i+1]-nodes[i])
            return values[i]+f*(values[i+1]-values[i])
    return 0.0

tables = {
    "sigma24": (sigma24, 15.42 , 1000.0, 100, True ),
    "sigma26": (sigma26, 30.0  ,   90.0, 100, False),
    "sigma28": (sigma28, 14.159,   17.7, 100, False),
}

def crossSection(name, energy):
    function, minimum, maximum, count, logarithmic = tables[name]
    nodes, values = tabulate(function, minimum, maximum, count, logarithmic)
    return interpolate(nodes, values, energy, logarithmic)

# --- the reference grids -----------------------------------------------------------------------

temperaturesKelvin     = [1.0e1, 1.0e2, 1.0e3, 6.0e3, 1.0e4, 1.0e5]
temperaturesElectronVolts = [1.0e-2, 1.0e-1, 1.0e0, 1.0e1, 1.0e2]
energiesSigma24        = [16.0, 17.0, 20.0, 50.0, 200.0]
energiesSigma26        = [35.0, 50.0, 70.0, 85.0]
energiesSigma28        = [15.0, 16.0, 17.0, 17.5]

def selfCheck():
    print("Cost of the tabulation: fit versus its interpolation on Galacticus' grid")
    for name, energies in (("sigma24", energiesSigma24), ("sigma26", energiesSigma26), ("sigma28", energiesSigma28)):
        function = tables[name][0]
        worst = max(abs(crossSection(name, e)-function(e))/function(e) for e in energies if function(e) > 0.0)
        print("  %-9s worst relative difference %.2e" % (name, worst))

def fortranArray(values):
    return "[" + ",".join(("%.14e" % v).replace("e", "d") for v in values) + "]"

def main():
    parser = argparse.ArgumentParser(description="Reference values for the primordial hydrogen network.")
    parser.add_argument("--self-check", action="store_true", help="report how much the tabulation costs")
    parser.add_argument("--fortran"   , action="store_true", help="emit Fortran array constructors")
    arguments = parser.parse_args()
    if arguments.self_check:
        selfCheck()
        return
    rows = [
        ("temperaturesKelvin"        , temperaturesKelvin           , None),
        ("rateCoefficientK7Reference" , [k7 (t) for t in temperaturesKelvin        ], None),
        ("rateCoefficientK16Reference", [k16(t) for t in temperaturesKelvin        ], None),
        ("temperaturesElectronVolts" , temperaturesElectronVolts    , None),
        ("rateCoefficientK8Reference" , [k8 (t) for t in temperaturesElectronVolts ], None),
        ("rateCoefficientK14Reference", [k14(t) for t in temperaturesElectronVolts ], None),
        ("energiesSigma24"           , energiesSigma24              , None),
        ("crossSection24Reference"   , [crossSection("sigma24", e) for e in energiesSigma24], None),
        ("energiesSigma26"           , energiesSigma26              , None),
        ("crossSection26Reference"   , [crossSection("sigma26", e) for e in energiesSigma26], None),
        ("energiesSigma28"           , energiesSigma28              , None),
        ("crossSection28Reference"   , [crossSection("sigma28", e) for e in energiesSigma28], None),
    ]
    if arguments.fortran:
        for name, values, _ in rows:
            print("%-28s=%s" % (name, fortranArray(values)))
        return
    for name, values, _ in rows:
        print("%-28s %s" % (name, " ".join("%.8e" % v for v in values)))

if __name__ == "__main__":
    main()
