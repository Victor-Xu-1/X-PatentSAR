"""Reviewed ADMET probabilities already produced by the single pinned model."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from .errors import WebError

if TYPE_CHECKING:
    from .analysis_models import Prediction

# Direction refers to the dataset label, not to an experimental safety claim.
LEAD_ENDPOINTS = {
    "hERG": "lower",
    "AMES": "lower",
    "DILI": "lower",
    "ClinTox": "lower",
    "HIA_Hou": "higher",
    "Bioavailability_Ma": "higher",
    "CYP1A2_Veith": "lower",
    "CYP2C9_Veith": "lower",
    "CYP2C19_Veith": "lower",
    "CYP2D6_Veith": "lower",
    "CYP3A4_Veith": "lower",
}


def validate_endpoints(value: object) -> object:
    if not isinstance(value, dict) or len(value) > len(LEAD_ENDPOINTS):
        raise ValueError("ADMET endpoint inventory exceeds its reviewed bound")
    for key, scalar in value.items():
        if (
            key not in LEAD_ENDPOINTS
            or type(scalar) not in {int, float}
            or not math.isfinite(scalar)
            or not 0 <= scalar <= 1
        ):
            raise ValueError("ADMET endpoint must be a reviewed finite probability")
    return value


def selected_endpoints(prediction: Prediction) -> dict[str, float]:
    """Never clamp physical regressions or derive safety from missing predictions."""
    supplied = {item.key: item for item in prediction.properties}
    if len(supplied) != len(prediction.properties):
        raise WebError(502, "admet_protocol", "ADMET endpoint keys are duplicated.")
    result = {}
    for key in LEAD_ENDPOINTS:
        item = supplied.get(key)
        if item is None:
            continue
        if item.unit != "probability [0,1]" or item.kind != "prediction":
            raise WebError(502, "admet_protocol", "Lead ADMET semantics differ.")
        result[key] = item.value
    try:
        validate_endpoints(result)
    except ValueError as exc:
        raise WebError(
            502, "admet_protocol", "Lead ADMET probability is invalid."
        ) from exc
    return result
