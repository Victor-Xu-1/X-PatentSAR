"""Shared bounded raw-artifact scalar and geometry validation."""

from __future__ import annotations

import math
from typing import Any

from .errors import WebError


def text(value: object, *, limit: int = 1000) -> str | None:
    if value is None:
        return None
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        raise WebError(
            422, "invalid_artifact", "Artifact contains invalid scalar metadata."
        )
    if isinstance(value, float) and not math.isfinite(value):
        raise WebError(
            422, "invalid_artifact", "Artifact contains a non-finite number."
        )
    return str(value)[:limit]


def page_number(value: object) -> int | None:
    if value in (None, 0, ""):
        return None
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise WebError(422, "invalid_artifact", "Artifact page number is invalid.")
    try:
        page = int(value)
    except (ValueError, TypeError, OverflowError) as exc:
        raise WebError(
            422, "invalid_artifact", "Artifact page number is invalid."
        ) from exc
    if not 1 <= page <= 20000:
        raise WebError(
            422, "invalid_artifact", "Artifact page number is outside bounds."
        )
    return page


def box(binding: dict[str, Any], structure: dict[str, Any]) -> list[float] | None:
    value = structure.get("bbox_pdf")
    if value is None and all(
        k in binding for k in ("struct_x0", "struct_y0", "struct_x1", "struct_y1")
    ):
        value = [
            binding[k] for k in ("struct_x0", "struct_y0", "struct_x1", "struct_y1")
        ]
    if value is None:
        return None
    if not isinstance(value, list) or len(value) != 4:
        raise WebError(422, "invalid_geometry", "Artifact geometry is invalid.")
    try:
        bounds = [float(x) for x in value]
    except (TypeError, ValueError, OverflowError) as exc:
        raise WebError(
            422, "invalid_geometry", "Artifact geometry is invalid."
        ) from exc
    if (
        not all(math.isfinite(x) and abs(x) <= 100000 for x in bounds)
        or bounds[2] <= bounds[0]
        or bounds[3] <= bounds[1]
    ):
        raise WebError(
            422, "invalid_geometry", "Artifact geometry is non-finite or inverted."
        )
    return bounds
