"""Lossless scalar, censored/interval and explicitly ordered grade semantics."""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from ..measurement_literals import NumericLiteralError, parse_numeric_literal
from .errors import SARInputError
from .limits import MAX_GRADES, MAX_VALUE_CHARS

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


def parse_value(raw: str, ranks: dict[str, int]) -> Value:
    if len(raw) > MAX_VALUE_CHARS:
        raise SARInputError("value_limit_exceeded")
    text = raw.strip()
    if text.casefold() in MISSING:
        return Value("missing")
    if text in ranks:
        return Value("ordinal", grade=text)
    try:
        numeric = parse_numeric_literal(raw)
        return Value(
            numeric.kind,
            numeric.low,
            numeric.high,
            numeric.lower_closed,
            numeric.upper_closed,
        )
    except NumericLiteralError as error:
        if error.code != "unsupported_measurement_value":
            raise SARInputError(error.code) from None
    if re.fullmatch(r"[^\W\d_]+|\++", text, flags=re.UNICODE):
        raise SARInputError("grade_order_required" if not ranks else "unknown_grade")
    raise SARInputError("unsupported_measurement_value")


def strictly_below(left: Value, right: Value, *, open_bounds: bool = True) -> bool:
    """Every possible left value is less than every possible right value.

    Touching finite endpoints prove strict order if either excludes that point.
    The opt-out is only for read-only previews of archived pre-v3 study inputs;
    new calculations and Pareto ordering always use the exact interval proof.
    """
    _, high = left.numeric_bounds()
    low, _ = right.numeric_bounds()
    return high < low or (
        open_bounds
        and high == low
        and high.is_finite()
        and not (left.upper_closed and right.lower_closed)
    )


def compare_values(
    reference: Value,
    candidate: Value,
    direction: str,
    ranks: dict[str, int],
    *,
    open_bounds: bool = True,
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
    reference_low, _ = reference.numeric_bounds()
    candidate_low, _ = candidate.numeric_bounds()
    if reference.kind == candidate.kind == "scalar" and reference_low == candidate_low:
        return "equal", None
    if strictly_below(candidate, reference, open_bounds=open_bounds):
        return ("better" if direction == "lower" else "worse"), None
    if strictly_below(reference, candidate, open_bounds=open_bounds):
        return ("better" if direction == "higher" else "worse"), None
    return "indeterminate", "intervals_not_strictly_separated"
