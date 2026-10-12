"""Shared numeric endpoint conventions, not medicinal desirability or grading."""

from __future__ import annotations

import re
import unicodedata

from ..core.potency_bands import concentration_unit
from .activity_rank_models import RankDirection

_POTENCY = re.compile(
    r"(?<!\w)(p?)(?:(?:ic|ec|dc|ac|gi|xc)[ _-]*(?:20|30|50|80|90|95)|k[ _-]*[id])(?!\w)"
)
_DIMENSIONLESS = {"", "1", "-", "unitless", "dimensionless", "ratio"}
_PERCENT = {"%", "percent"}
_EFFECT = re.compile(r"\binhibition\b|\bdegradation\b")
_REMAINING = re.compile(r"\bviability\b|\bremaining\b|\bresidual\b")


def numeric_direction(
    name: str, unit: str | None, assay: str | None
) -> tuple[RankDirection, str]:
    """Known semantic polarity only. Never fill units, values or assay conditions."""
    label = unicodedata.normalize("NFKC", name).casefold()
    normalized_unit = (
        (unit or "").strip().casefold().replace("μ", "u").replace("µ", "u")
    )
    matches = list(_POTENCY.finditer(label))
    if matches:
        if len(matches) != 1 or re.search(
            r"\blog(?:10)?\b|\bratio\b|\bfold\b|\bselectivity\b|\bdifference\b", label
        ):
            return "unknown", "ambiguous_endpoint"
        if matches[0].group(1):
            return (
                ("higher", "log_potency")
                if normalized_unit in _DIMENSIONLESS
                else ("unknown", "unit_conflict")
            )
        return (
            ("lower", "potency")
            if not normalized_unit or concentration_unit(unit)
            else ("unknown", "unit_conflict")
        )
    dimensionless = normalized_unit in _DIMENSIONLESS
    percent = normalized_unit in _PERCENT
    if re.search(r"\by[ _-]?min\b", label):
        context = label + " " + (assay or "").casefold()
        if (dimensionless or percent) and re.search(r"prolif|degrad", context):
            return "lower", "ymin_remaining"
        return "unknown", "unknown_ymin_context_or_unit"
    if re.search(r"\bd[ _-]?max\b", label):
        return (
            ("higher", "effect_percent")
            if dimensionless or percent
            else ("unknown", "unit_conflict")
        )
    if (
        dimensionless
        and re.search(r"\bhtrf\s+ratio\b", label)
        and (assay or "").strip().casefold() == "htrf"
    ):
        return "lower", "htrf_competition"
    if percent:
        effect, remaining = bool(_EFFECT.search(label)), bool(_REMAINING.search(label))
        if effect != remaining:
            return (
                ("higher", "effect_percent")
                if effect
                else ("lower", "remaining_percent")
            )
    return "unknown", "unknown"
