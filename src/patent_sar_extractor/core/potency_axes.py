"""Exact concentration-decade coordinates; never exponentiate rounded log values."""

from decimal import ROUND_FLOOR, Decimal
from typing import Literal

from .sar.values import Value

PotencyBasis = Literal["concentration", "negative_log_molar"]
ZERO, INFINITY = Decimal(0), Decimal("Infinity")
UNKNOWN = Value("interval", -INFINITY, INFINITY, False, False)


def reverse_range(value: Value) -> Value:
    low, high = value.numeric_bounds()
    return Value(
        value.kind,
        high.copy_negate(),
        low.copy_negate(),
        value.upper_closed,
        value.lower_closed,
    )


def potency_range(value: Value, basis: PotencyBasis) -> Value | None:
    if value.kind not in {"scalar", "interval"}:
        return None
    if basis == "negative_log_molar":
        return reverse_range(value)
    if basis != "concentration":
        raise ValueError("unsupported_potency_basis")
    low, high = value.numeric_bounds()
    if high <= 0 or (value.kind == "scalar" and low <= 0):
        return None
    return Value(
        value.kind,
        max(ZERO, low),
        high,
        value.lower_closed if low > 0 else False,
        value.upper_closed,
    )


def decade_bounds(low: Decimal, high: Decimal, high_closed: bool, basis: PotencyBasis):
    """Return the same decade only if the entire tenth-rank interval proves it."""
    if not low.is_finite() or not high.is_finite():
        return None
    if basis == "negative_log_molar":
        # These are -pActivity coordinates, exactly log10(concentration/M).
        lower = int(low.to_integral_value(rounding=ROUND_FLOOR))
        upper = int(high.to_integral_value(rounding=ROUND_FLOOR))
        if not high_closed and high == upper:
            upper -= 1
    else:
        if low <= 0:
            return None
        lower, upper = low.adjusted(), high.adjusted()
        if not high_closed and high == Decimal(1).scaleb(upper):
            upper -= 1
    if lower != upper or not -308 <= lower <= 306:
        return None
    return lower
