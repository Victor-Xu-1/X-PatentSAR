"""Lossless scalar, censored/interval and explicitly ordered grade semantics."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from .errors import SARInputError
from .limits import MAX_GRADES, MAX_VALUE_CHARS

NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
MISSING = {
    "",
    "na",
    "n/a",
    "nd",
    "nt",
    "none",
    "null",
    "-",
    "—",
    "not determined",
    "not tested",
    "not available",
}


@dataclass(frozen=True)
class Value:
    kind: str
    low: Decimal | None = None
    high: Decimal | None = None
    lower_closed: bool = True
    upper_closed: bool = True
    grade: str | None = None

    def numeric_bounds(self) -> tuple[Decimal, Decimal]:
        if (
            self.kind not in {"scalar", "interval"}
            or self.low is None
            or self.high is None
        ):
            raise SARInputError("invalid_numeric_value")
        return self.low, self.high


def grade_ranks(order: object) -> dict[str, int]:
    if not isinstance(order, (list, tuple)) or len(order) > MAX_GRADES:
        raise SARInputError("invalid_grade_order")
    if any(
        not isinstance(item, str)
        or not item
        or len(item) > MAX_VALUE_CHARS
        or item != item.strip()
        for item in order
    ):
        raise SARInputError("invalid_grade_order")
    if len(set(order)) != len(order):
        raise SARInputError("invalid_grade_order")
    return {item: i for i, item in enumerate(order)}


def _number(text: str) -> Decimal:
    try:
        value = Decimal(text)
        if not value.is_finite() or not -308 <= value.adjusted() <= 308:
            raise SARInputError("numeric_limit_exceeded")
        return value
    except InvalidOperation:
        raise SARInputError("invalid_numeric_value") from None


def parse_value(raw: str, ranks: dict[str, int]) -> Value:
    if len(raw) > MAX_VALUE_CHARS:
        raise SARInputError("value_limit_exceeded")
    text = raw.strip()
    if text.casefold() in MISSING:
        return Value("missing")
    if text in ranks:
        return Value("ordinal", grade=text)
    if re.fullmatch(NUMBER, text):
        scalar = _number(text)
        return Value("scalar", scalar, scalar)
    match = re.fullmatch(rf"(<=|>=|<|>|≤|≥)\s*({NUMBER})", text)
    if match:
        bound = _number(match[2])
        if match[1] in {"<", "<=", "≤"}:
            return Value(
                "interval", Decimal("-Infinity"), bound, False, match[1] != "<"
            )
        return Value("interval", bound, Decimal("Infinity"), match[1] != ">", False)
    bracket = re.fullmatch(rf"([\[(])\s*({NUMBER})\s*,\s*({NUMBER})\s*([\])])", text)
    ranged = re.fullmatch(rf"({NUMBER})\s*(?:-|–|—|\.\.)\s*({NUMBER})", text)
    if bracket or ranged:
        if bracket:
            low, high = _number(bracket[2]), _number(bracket[3])
        elif ranged:
            low, high = _number(ranged[1]), _number(ranged[2])
        lower_closed = not bracket or bracket[1] == "["
        upper_closed = not bracket or bracket[4] == "]"
        if low > high or (low == high and not (lower_closed and upper_closed)):
            raise SARInputError("invalid_interval")
        return Value("interval", low, high, lower_closed, upper_closed)
    if re.fullmatch(r"[^\W\d_]+|\++", text, flags=re.UNICODE):
        raise SARInputError("grade_order_required" if not ranks else "unknown_grade")
    raise SARInputError("unsupported_measurement_value")


def compare_values(
    reference: Value, candidate: Value, direction: str, ranks: dict[str, int]
) -> tuple[str, str | None]:
    if reference.kind == "ordinal" or candidate.kind == "ordinal":
        if reference.kind != candidate.kind:
            return "indeterminate", "mixed_measurement_kinds"
        if reference.grade is None or candidate.grade is None:
            raise SARInputError("invalid_grade_value")
        if reference.grade == candidate.grade:
            return "indeterminate", "same_grade_not_quantitative"
        return (
            "better" if ranks[candidate.grade] < ranks[reference.grade] else "worse"
        ), None
    reference_low, reference_high = reference.numeric_bounds()
    candidate_low, candidate_high = candidate.numeric_bounds()
    if reference.kind == candidate.kind == "scalar" and reference_low == candidate_low:
        return "equal", None
    # Even open intervals touching at one endpoint are not strictly separated.
    if candidate_high < reference_low:
        return ("better" if direction == "lower" else "worse"), None
    if candidate_low > reference_high:
        return ("better" if direction == "higher" else "worse"), None
    return "indeterminate", "intervals_not_strictly_separated"
