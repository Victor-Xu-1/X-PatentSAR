"""Exact interpretation of an explicit inline unit in a declared measurement unit.

Only molar SI prefixes and percent are supported here. Source strings stay
immutable. Intake may choose a standard basis from an explicit numeric suffix;
bare cells never inherit an unstated unit from their neighbours. This does not
merge declared columns/experiments or convert mass concentration, p-values or PK.
"""

from __future__ import annotations

import math
import re
from decimal import Decimal, localcontext

from .errors import SARInputError
from .limits import MAX_VALUE_CHARS
from .values import Value, parse_value

_MOLAR = {"fM": -15, "pM": -12, "nM": -9, "uM": -6, "mM": -3, "M": 0}
_PERCENT = {"%", "％", "percent", "percentage"}
_SUFFIX = re.compile(r"(.+?)\s*(fM|pM|nM|[uµμ]M|mM|M|%|％)\s*", re.DOTALL)


def scalar_difference(left: Value, right: Value) -> float | None:
    """Exact candidate minus reference, never a midpoint or a rounded false zero."""
    if left.kind != "scalar" or right.kind != "scalar":
        return None
    a, b = left.numeric_bounds()[0], right.numeric_bounds()[0]
    exponent_a, exponent_b = a.as_tuple().exponent, b.as_tuple().exponent
    if not isinstance(exponent_a, int) or not isinstance(exponent_b, int):
        return None
    with localcontext() as context:
        context.prec = max(a.adjusted(), b.adjusted()) - min(exponent_a, exponent_b) + 2
        difference = b - a
        value = float(difference)
    if not math.isfinite(value) or (value == 0 and difference != 0):
        return None
    return value


def _unit(text: str | None) -> tuple[str, int] | None:
    symbol = (text or "").strip().replace("µ", "u").replace("μ", "u")
    if symbol in _MOLAR:
        return "molar", _MOLAR[symbol]
    if symbol.casefold() in _PERCENT:
        return "percent", 0
    return None


def _scale(value: Decimal, shift: int) -> Decimal:
    if not value.is_finite():
        return value
    sign, digits, exponent = value.as_tuple()
    assert isinstance(exponent, int)
    # Tuple construction changes only the base-10 exponent; scaleb/multiplication
    # under the process Decimal context could round a long original coefficient.
    result = Decimal((sign, digits, exponent + shift))
    if not -308 <= result.adjusted() <= 308:
        raise SARInputError("numeric_limit_exceeded")
    return result


def explicit_unit_basis(raw: str) -> str | None:
    """A calculation basis only when the original cell explicitly names a unit."""
    if len(raw) > MAX_VALUE_CHARS:
        return None
    suffix = _SUFFIX.fullmatch(raw.strip())
    if suffix is None:
        return None
    try:
        value = parse_value(suffix[1].strip(), {})
    except SARInputError:
        return None
    unit = _unit(suffix[2])
    if value.kind not in {"scalar", "interval"} or unit is None:
        return None
    return "nM" if unit[0] == "molar" else "%"


def parse_measurement(
    raw: str,
    ranks: dict[str, int],
    unit: str | None,
    *,
    inline_units: bool = True,
) -> Value:
    if len(raw) > MAX_VALUE_CHARS:
        raise SARInputError("value_limit_exceeded")
    if not inline_units or raw.strip() in ranks:
        return parse_value(raw, ranks)
    suffix = _SUFFIX.fullmatch(raw.strip())
    if suffix is None:
        return parse_value(raw, ranks)
    source, target = _unit(suffix[2]), _unit(unit)
    if not unit or not unit.strip():
        raise SARInputError("unit_missing")
    if source is None or target is None or source[0] != target[0]:
        raise SARInputError("unit_conflict")
    value = parse_value(suffix[1].strip(), ranks)
    if value.kind not in {"scalar", "interval"}:
        raise SARInputError("unsupported_measurement_value")
    low, high = value.numeric_bounds()
    shift = source[1] - target[1]
    return Value(
        value.kind,
        _scale(low, shift),
        _scale(high, shift),
        value.lower_closed,
        value.upper_closed,
    )
