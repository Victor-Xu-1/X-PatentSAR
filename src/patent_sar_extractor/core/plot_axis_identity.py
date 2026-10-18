"""Exact bounded numeric spelling identity, only for original graph ticks."""

import re
from decimal import Decimal, InvalidOperation

_NUMBER = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d{1,3})?%?")


def axis_number(text):
    """Preserve all finite tick precision; no measurement or identifier repair."""
    if not isinstance(text, str) or len(text) > 64:
        return None
    raw = text.strip().replace("−", "-")
    if not _NUMBER.fullmatch(raw):
        return None
    try:
        value = Decimal(raw.rstrip("%"))
    except InvalidOperation:
        return None
    return value if value.is_finite() else None


def axis_literal(text):
    """Comparison key without rounding, unit erasure or changing original text."""
    value = axis_number(text)
    if value is None:
        return None
    unit = "%" if text.strip().endswith("%") else ""
    if value.is_zero():
        return "number:0" + unit
    sign, digits, exponent = value.as_tuple()
    # Decimal.normalize() can round under the caller's context. Strip only
    # representational trailing zeroes from the exact coefficient instead.
    digits = list(digits)
    while digits[-1] == 0:
        digits.pop()
        exponent += 1
    coefficient = ("-" if sign else "") + "".join(map(str, digits))
    return f"number:{coefficient}e{exponent}{unit}"
