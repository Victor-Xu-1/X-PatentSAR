"""One exact-scalar parser and explicit supported indicator conventions."""

from __future__ import annotations

import math
import re

from .activity_rank_models import RankDirection, RankKind

_NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]{1,3})?")
_POTENCY = r"(?:(?:ic|ec|dc|ac|gi)(?:30|50|90)|ki|kd)"


def rank_value(value: object) -> tuple[RankKind, float] | None:
    """Censored, ranged, missing and mixed-unit text stays unranked, unchanged."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            number = float(value)
        except OverflowError:
            return None
        return ("numeric", number) if math.isfinite(number) else None
    if not isinstance(value, str) or len(value) > 1000:
        return None
    scalar = value.strip()
    if re.fullmatch(r"\+{1,8}", scalar):
        return "plus", float(len(scalar))
    if re.fullmatch(r"[A-Z]", scalar):
        return "letter", float(ord(scalar) - ord("A"))
    if _NUMBER.fullmatch(scalar):
        number = float(scalar)
        return ("numeric", number) if math.isfinite(number) else None
    return None


def rank_direction(
    name: str, unit: str | None, assay: str | None, kind: RankKind
) -> tuple[RankDirection, str]:
    label = name.casefold()
    if kind == "plus":
        return "higher", "plus_count"
    if (
        kind == "letter"
        and "degradation grade" in label
        and (assay or "").casefold() == "western blot"
    ):
        return "lower", "western_grade"
    if kind != "numeric":
        return "unknown", "unknown"
    if re.search(rf"\bp{_POTENCY}\b", label):
        return "higher", "log_potency"
    if re.search(rf"\b{_POTENCY}\b", label):
        return "lower", "potency"
    if re.search(r"\bhtrf\s+ratio\b", label) and (assay or "").casefold() == "htrf":
        return "lower", "htrf_competition"
    if (unit or "").strip().casefold() in {"%", "percent"}:
        if re.search(r"\binhibition\b|\bdegradation\b", label):
            return "higher", "effect_percent"
        if re.search(r"\bviability\b|\bremaining\b|\bresidual\b", label):
            return "lower", "remaining_percent"
    return "unknown", "unknown"
