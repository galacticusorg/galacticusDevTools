#!/usr/bin/env python3
"""Independent reference values for the Chabrier (2001) stellar initial mass function.

Galacticus' `initialMassFunctionChabrier2001` implements the initial mass function of Chabrier (2001, ApJ, 554, 1274) as a
log-normal in log(M) below a transition mass, joined to a power law above it:

    phi(M) = A exp( -[log10(M/M_c)/sigma]^2 / 2 ) / M     for M_l <= M < M_t
    phi(M) = B M^alpha                                    for M_t <= M < M_u
    phi(M) = 0                                            otherwise

normalized so that the total *mass* is unity, i.e. the integral of M phi(M) dM over [M_l, M_u] is 1.

This script derives the normalization analytically rather than transcribing the code's expressions. The mass integral of the
log-normal piece has a closed form: writing t = log10(M/M_c), so that M = M_c 10^t and dM = M_c ln10 10^t dt,

    Int M phi dM = A M_c ln10 Int exp( -t^2/2 sigma^2 + t ln10 ) dt
                 = A M_c ln10 exp( sigma^2 ln^2(10) / 2 ) sigma sqrt(pi/2) [ erf(s_t) - erf(s_l) ]

with s = log10(M/M_c)/(sigma sqrt2) - sigma ln10 / sqrt2. The power-law piece integrates trivially. Both are checked here
against direct numerical quadrature.

One property worth testing rather than assuming: requiring the two branches to join continuously at M_t fixes B, and doing so
gives phi_PL(M_t)/phi_LN(M_t) = M_t^alpha under the normalization Galacticus uses. That equals one only for M_t = 1 Msun,
which is the default. The continuity of the implemented form as a function of M_t is therefore measured below rather than
asserted.

Andrew Benson, Claude (15-September-2026).
"""

import numpy as np
from scipy.special import erf
from scipy.integrate import quad

# Galacticus defaults, which are the values of Chabrier (2001) for the Galactic disk.
massLowerDefault          = 0.1
massTransitionDefault     = 1.0
massUpperDefault          = 125.0
massCharacteristicDefault = 0.08
sigmaDefault              = 0.69
exponentDefault           = -2.3


def _sArgument(mass, massCharacteristic, sigma):
    """The error-function argument arising from completing the square in the log-normal mass integral."""
    return np.log10(mass / massCharacteristic) / (sigma * np.sqrt(2.0)) - sigma * np.log(10.0) / np.sqrt(2.0)


def massIntegralLogNormal(massLower, massUpper, massCharacteristic, sigma):
    """Integral of M phi(M) dM over the log-normal branch, for unit coefficient A, in closed form."""
    if massUpper <= massLower:
        return 0.0
    return (
        massCharacteristic
        * np.log(10.0)
        * np.exp(0.5 * sigma ** 2 * np.log(10.0) ** 2)
        * sigma
        * np.sqrt(np.pi / 2.0)
        * (erf(_sArgument(massUpper, massCharacteristic, sigma)) - erf(_sArgument(massLower, massCharacteristic, sigma)))
    )


def massIntegralPowerLaw(massLower, massUpper, exponent):
    """Integral of M^(1+alpha) dM over the power-law branch, for unit coefficient B."""
    if massUpper <= massLower:
        return 0.0
    return (massUpper ** (2.0 + exponent) - massLower ** (2.0 + exponent)) / (2.0 + exponent)


class Chabrier2001:
    """The Chabrier (2001) initial mass function, normalized to unit total mass."""

    def __init__(
        self,
        massLower=massLowerDefault,
        massTransition=massTransitionDefault,
        massUpper=massUpperDefault,
        massCharacteristic=massCharacteristicDefault,
        sigma=sigmaDefault,
        exponent=exponentDefault,
    ):
        self.massLower, self.massTransition, self.massUpper = massLower, massTransition, massUpper
        self.massCharacteristic, self.sigma, self.exponent = massCharacteristic, sigma, exponent
        # Coefficient of the power-law branch relative to the log-normal one, fixed by requiring the two branches to join
        # continuously at the transition mass: phi_LN(M_t) = phi_PL(M_t) gives B = exp(...) / M_t^(1+alpha).
        self._powerLawRelative = np.exp(
            -0.5 * np.log10(massTransition / massCharacteristic) ** 2 / sigma ** 2
        ) / massTransition ** (1.0 + exponent)
        # Total mass with unit log-normal coefficient.
        total = massIntegralLogNormal(massLower, massTransition, massCharacteristic, sigma) + self._powerLawRelative * (
            massIntegralPowerLaw(massTransition, massUpper, exponent)
        )
        self.normalizationLogNormal = 1.0 / total
        self.normalizationPowerLaw = self._powerLawRelative / total

    def phi(self, mass):
        """dN/dM, normalized to unit total stellar mass formed."""
        mass = np.asarray(mass, dtype=float)
        result = np.zeros_like(mass)
        inLogNormal = (mass >= self.massLower) & (mass < self.massTransition)
        inPowerLaw = (mass >= self.massTransition) & (mass < self.massUpper)
        result[inLogNormal] = (
            self.normalizationLogNormal
            * np.exp(-0.5 * (np.log10(mass[inLogNormal] / self.massCharacteristic) / self.sigma) ** 2)
            / mass[inLogNormal]
        )
        result[inPowerLaw] = self.normalizationPowerLaw * mass[inPowerLaw] ** self.exponent
        return result if result.shape else float(result)

    def numberCumulative(self, massLower, massUpper):
        """Number of stars formed between two masses, per unit total mass formed, in closed form."""
        number = 0.0
        lower, upper = max(massLower, self.massLower), min(massUpper, self.massTransition)
        if upper > lower:
            number += (
                np.sqrt(np.pi / 2.0)
                * np.log(10.0)
                * self.sigma
                * self.normalizationLogNormal
                * (
                    erf(np.log10(upper / self.massCharacteristic) / np.sqrt(2.0) / self.sigma)
                    - erf(np.log10(lower / self.massCharacteristic) / np.sqrt(2.0) / self.sigma)
                )
            )
        lower, upper = max(massLower, self.massTransition), min(massUpper, self.massUpper)
        if upper > lower:
            number += (
                self.normalizationPowerLaw
                / (1.0 + self.exponent)
                * (upper ** (1.0 + self.exponent) - lower ** (1.0 + self.exponent))
            )
        return number

    def massTotal(self):
        """Total mass, by direct quadrature. Must be unity."""
        value, _ = quad(lambda m: m * float(self.phi(m)), self.massLower, self.massUpper, limit=400, points=[self.massTransition])
        return value

    def continuityRatio(self):
        """phi just above the transition mass divided by phi just below it. Unity if the branches join continuously."""
        below = float(self.phi(self.massTransition * (1.0 - 1.0e-12)))
        above = float(self.phi(self.massTransition * (1.0 + 1.0e-12)))
        return above / below


if __name__ == "__main__":
    imf = Chabrier2001()
    print("Chabrier (2001) initial mass function reference values")
    print(
        f"  M_l = {imf.massLower}, M_t = {imf.massTransition}, M_u = {imf.massUpper}, "
        f"M_c = {imf.massCharacteristic}, sigma = {imf.sigma}, alpha = {imf.exponent}"
    )
    print(f"  normalization (log-normal branch) = {imf.normalizationLogNormal:.10e}")
    print(f"  normalization (power-law branch)  = {imf.normalizationPowerLaw:.10e}")
    print()

    print(f"  total mass by quadrature = {imf.massTotal():.12f}   (must be 1)")
    print(f"  total number of stars per unit mass = {imf.numberCumulative(imf.massLower, imf.massUpper):.10e}")
    print()

    # Check the closed-form branch integrals against quadrature.
    closedLogNormal = massIntegralLogNormal(imf.massLower, imf.massTransition, imf.massCharacteristic, imf.sigma)
    numericLogNormal, _ = quad(
        lambda m: np.exp(-0.5 * (np.log10(m / imf.massCharacteristic) / imf.sigma) ** 2),
        imf.massLower,
        imf.massTransition,
        limit=400,
    )
    print("  Closed-form branch mass integrals against quadrature:")
    print(
        f"    log-normal: closed {closedLogNormal:.12e}  quadrature {numericLogNormal:.12e}  "
        f"relative difference {abs(closedLogNormal / numericLogNormal - 1.0):.2e}"
    )
    closedPowerLaw = massIntegralPowerLaw(imf.massTransition, imf.massUpper, imf.exponent)
    numericPowerLaw, _ = quad(lambda m: m ** (1.0 + imf.exponent), imf.massTransition, imf.massUpper, limit=400)
    print(
        f"    power law : closed {closedPowerLaw:.12e}  quadrature {numericPowerLaw:.12e}  "
        f"relative difference {abs(closedPowerLaw / numericPowerLaw - 1.0):.2e}"
    )
    print()

    print("  phi(M), for the unit test:")
    print(f"    {'M [Msun]':>12}  {'phi(M)':>20}  branch")
    for mass in (0.15, 0.3, 0.5, 0.8, 1.5, 5.0, 20.0, 100.0):
        branch = "log-normal" if mass < imf.massTransition else "power law"
        print(f"    {mass:12.4f}  {float(imf.phi(mass)):20.10e}  {branch}")
    print()

    print("  Cumulative numbers, for the unit test:")
    for lower, upper in ((0.1, 1.0), (1.0, 8.0), (8.0, 125.0), (0.1, 125.0)):
        print(f"    N({lower:6.2f} to {upper:7.2f}) = {imf.numberCumulative(lower, upper):.10e}")
    print()

    # Continuity at the transition mass, as a function of the transition mass. The ratio should be M_t^alpha if the analysis
    # above is right, which is unity only for M_t = 1.
    print("  Continuity at the transition mass (phi above / phi below):")
    print(f"    {'M_t':>8}  {'ratio':>18}  {'M_t^alpha':>18}")
    for massTransition in (0.5, 0.8, 1.0, 1.5, 2.0):
        imfAlternate = Chabrier2001(massTransition=massTransition)
        ratio = imfAlternate.continuityRatio()
        print(f"    {massTransition:8.3f}  {ratio:18.10f}  {massTransition ** exponentDefault:18.10f}")
