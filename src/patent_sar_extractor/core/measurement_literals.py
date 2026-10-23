"""One exact bounded numeric grammar for original intake and SAR interpretation."""

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Literal

MAX_NUMERIC_LITERAL_CHARS = 256
NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
_CENSORED = rf"(<=|>=|<|>|≤|≥)\s*({NUMBER})"
_BRACKET = rf"([\[(])\s*({NUMBER})\s*,\s*({NUMBER})\s*([\])])"
_RANGE = rf"({NUMBER})\s*(?:-|–|—|\.\.)\s*({NUMBER})"
NUMERIC_LITERAL_PATTERN = rf"(?:{_BRACKET}|{_RANGE}|{_CENSORED}|{NUMBER})"


class NumericLiteralError(ValueError):
    """Stable nonraw error codes; domain adapters keep their own error type."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class NumericLiteral:
    kind: Literal["scalar", "interval"]
    low: Decimal
    high: Decimal
    lower_closed: bool = True
    upper_closed: bool = True


def _number(text: str) -> Decimal:
    try:
        value = Decimal(text)
        if not value.is_finite() or not -308 <= value.adjusted() <= 308:
            raise NumericLiteralError("numeric_limit_exceeded")
        return value
    except InvalidOperation:
        raise NumericLiteralError("invalid_numeric_value") from None


def parse_numeric_literal(raw: str) -> NumericLiteral:
    """Preserve exact endpoints and inclusivity; no units, grades or midpoint.

    This is the former SAR numeric authority, shared without increasing its
    supported forms or limits. Source strings are never normalized or rewritten.
    """
    if not isinstance(raw, str):
        raise NumericLiteralError("invalid_numeric_value")
    if len(raw) > MAX_NUMERIC_LITERAL_CHARS:
        raise NumericLiteralError("value_limit_exceeded")
    text = raw.strip()
    if re.fullmatch(NUMBER, text):
        scalar = _number(text)
        return NumericLiteral("scalar", scalar, scalar)
    match = re.fullmatch(_CENSORED, text)
    if match:
        bound = _number(match[2])
        if match[1] in {"<", "<=", "≤"}:
            return NumericLiteral(
                "interval", Decimal("-Infinity"), bound, False, match[1] != "<"
            )
        return NumericLiteral(
            "interval", bound, Decimal("Infinity"), match[1] != ">", False
        )
    bracket, ranged = re.fullmatch(_BRACKET, text), re.fullmatch(_RANGE, text)
    if bracket or ranged:
        low, high = (
            (_number(bracket[2]), _number(bracket[3]))
            if bracket
            else (_number(ranged[1]), _number(ranged[2]))
        )
        lower_closed, upper_closed = (
            not bracket or bracket[1] == "[",
            not bracket or bracket[4] == "]",
        )
        if low > high or (low == high and not (lower_closed and upper_closed)):
            raise NumericLiteralError("invalid_interval")
        return NumericLiteral("interval", low, high, lower_closed, upper_closed)
    raise NumericLiteralError("unsupported_measurement_value")
