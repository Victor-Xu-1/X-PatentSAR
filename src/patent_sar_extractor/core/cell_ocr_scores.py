"""One numeric-only OCR confidence boundary; invalid values remain unqualified."""

import math

import numpy as np


def confidence_value(value):
    if isinstance(value, (bool, np.bool_)) or not isinstance(
        value, (int, float, np.integer, np.floating)
    ):
        return None
    try:
        score = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return score if math.isfinite(score) and 0 <= score <= 1 else None


def confidence_score(value):
    """Existing score API; malformed metadata stays distinguishable to validators."""
    score = confidence_value(value)
    return score if score is not None else 0.0
