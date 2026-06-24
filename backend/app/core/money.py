"""Decimal helpers for monetary and quantity arithmetic.

All money and crypto amounts flow through ``Decimal`` end to end. ``float`` is
never used for fiscal figures: rounding errors are unacceptable in a tax tool.

Conventions
-----------
* EUR amounts are quantised to 2 decimal places (cents), ROUND_HALF_UP.
* Crypto quantities keep up to 18 decimals (wei-level precision).
* Per-unit costs/prices keep high precision (18 dp) and are only rounded when
  multiplied back into an EUR amount.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

EUR_QUANT = Decimal("0.01")
QTY_QUANT = Decimal("1E-18")

ZERO = Decimal("0")


def to_decimal(value: Any) -> Decimal:
    """Coerce arbitrary input to ``Decimal`` (never via float).

    Accepts Decimal/int/str. Floats are converted through ``str`` to avoid
    binary-float artefacts. Empty/None becomes 0.
    """
    if value is None or value == "":
        return ZERO
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        value = repr(value)
    try:
        return Decimal(str(value).strip().replace(",", "") if isinstance(value, str) else value)
    except (InvalidOperation, ValueError):
        raise ValueError(f"No se puede convertir a Decimal: {value!r}")


def quantize_eur(value: Any) -> Decimal:
    """Round to EUR cents (2 dp, half-up)."""
    return to_decimal(value).quantize(EUR_QUANT, rounding=ROUND_HALF_UP)


def quantize_qty(value: Any) -> Decimal:
    """Round a crypto quantity to 18 dp."""
    return to_decimal(value).quantize(QTY_QUANT, rounding=ROUND_HALF_UP)
