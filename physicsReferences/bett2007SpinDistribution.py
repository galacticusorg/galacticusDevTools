#!/usr/bin/env python3
"""Independent reference values for the Bett et al. (2007) halo spin distribution.

Galacticus' `haloSpinDistributionBett2007` implements the fitting function of Bett et al. (2007, MNRAS, 376, 215) for the
distribution of dark matter halo spin parameters:

    dP/dlambda = N (lambda/lambda_0)^3 exp[ -alpha (lambda/lambda_0)^(3/alpha) ] / lambda

Note the trailing 1/lambda: this is a density in lambda, not in ln(lambda), so the leading power is effectively lambda^2. That
factor is what makes the normalization come out as it does below, and it is the detail a reference written from the paper is
most likely to get wrong, so it is checked here numerically as well as analytically.

Normalization and moments follow in closed form. Substituting

    x = alpha (lambda/lambda_0)^(3/alpha)   =>   lambda = lambda_0 (x/alpha)^(alpha/3)

turns the distribution into a Gamma distribution of shape alpha,

    dP/dx = x^(alpha-1) e^-x / Gamma(alpha),

from which

    N              = 3 alpha^(alpha-1) / Gamma(alpha)
    <lambda^n>     = lambda_0^n alpha^(-n alpha/3) Gamma(alpha + n alpha/3) / Gamma(alpha)

This script evaluates those expressions, checks them against direct numerical quadrature of the distribution as written, and
tabulates reference values for the companion unit test.

Andrew Benson, Claude (15-September-2026).
"""

import numpy as np
from scipy.special import gamma
from scipy.integrate import quad

# Defaults of the Galacticus class, which are the values fit by Bett et al. (2007).
lambda0Default = 0.04326
alphaDefault   = 2.509


def normalization(alpha):
    """The normalization N = 3 alpha^(alpha-1) / Gamma(alpha)."""
    return 3.0 * alpha ** (alpha - 1.0) / gamma(alpha)


def distribution(spin, lambda0=lambda0Default, alpha=alphaDefault):
    """dP/dlambda, exactly as the fitting function is written."""
    return (
        normalization(alpha)
        * (spin / lambda0) ** 3
        * np.exp(-alpha * (spin / lambda0) ** (3.0 / alpha))
        / spin
    )


def moment(n, lambda0=lambda0Default, alpha=alphaDefault):
    """<lambda^n>, in closed form via the Gamma-distribution substitution."""
    return lambda0 ** n * alpha ** (-n * alpha / 3.0) * gamma(alpha + n * alpha / 3.0) / gamma(alpha)


def moment_numerical(n, lambda0=lambda0Default, alpha=alphaDefault):
    """<lambda^n> by direct quadrature, as an independent check of the closed form."""
    value, _ = quad(lambda s: s ** n * distribution(s, lambda0, alpha), 0.0, np.inf, limit=400)
    return value


if __name__ == "__main__":
    print("Bett et al. (2007) halo spin distribution reference values")
    print(f"  lambda_0 = {lambda0Default}, alpha = {alphaDefault}  (Galacticus defaults)")
    print(f"  normalization N = 3 alpha^(alpha-1) / Gamma(alpha) = {normalization(alphaDefault):.10e}")
    print()

    # Confirm the distribution as written integrates to unity. This validates both the normalization constant and the
    # trailing 1/lambda factor together: get either wrong and this is not 1.
    integral, _ = quad(lambda s: distribution(s), 0.0, np.inf, limit=400)
    print(f"  integral of dP/dlambda over (0, infinity) = {integral:.12f}   (must be 1)")
    print()

    print("  Moments, closed form against direct quadrature:")
    for n in (1, 2, 3):
        closed, numeric = moment(n), moment_numerical(n)
        print(
            f"    <lambda^{n}> = {closed:.10e}   quadrature {numeric:.10e}   relative difference {abs(numeric / closed - 1.0):.2e}"
        )
    mean = moment(1)
    sigma = np.sqrt(moment(2) - mean ** 2)
    print(f"    mean = {mean:.10e}, standard deviation = {sigma:.10e}")
    print()

    # Values of the distribution at a set of spins spanning the range of physical halo spins, for assertion in the unit test.
    print("  Distribution values, for the unit test:")
    print(f"    {'lambda':>14}  {'dP/dlambda':>18}")
    for spin in (5.0e-3, 1.0e-2, 2.0e-2, 4.326e-2, 8.0e-2, 1.5e-1):
        print(f"    {spin:14.6e}  {distribution(spin):18.10e}")
    print()

    # A non-default parameter pair, to check that the normalization really does track alpha rather than being a constant
    # absorbed into a tabulation.
    lambda0Alternate, alphaAlternate = 0.035, 3.0
    print(f"  Alternate parameters lambda_0 = {lambda0Alternate}, alpha = {alphaAlternate}:")
    print(f"    normalization = {normalization(alphaAlternate):.10e}")
    integralAlternate, _ = quad(lambda s: distribution(s, lambda0Alternate, alphaAlternate), 0.0, np.inf, limit=400)
    print(f"    integral = {integralAlternate:.12f}   (must be 1)")
    print(f"    mean     = {moment(1, lambda0Alternate, alphaAlternate):.10e}")
    print(f"    {'lambda':>14}  {'dP/dlambda':>18}")
    for spin in (1.0e-2, 3.5e-2, 1.0e-1):
        print(f"    {spin:14.6e}  {distribution(spin, lambda0Alternate, alphaAlternate):18.10e}")
