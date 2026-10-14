"""One numeric-only OCR confidence boundary; invalid values remain unqualified."""

import math

import numpy as np


def confidence_score(value):
    if isinstance(value, (bool, np.bool_)) or not isinstance(
        value, (int, float, np.integer, np.floating)
    ):
        return 0.0
    try:
        score = float(value)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    return score if math.isfinite(score) and 0 <= score <= 1 else 0.0
