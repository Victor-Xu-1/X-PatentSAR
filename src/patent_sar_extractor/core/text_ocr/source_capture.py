"""Shared unresolved-only original text capture, without scientific decisions."""

import copy

from .cell_capture import refine_text_pair
from .configuration import get_auxiliary_text_runtime
from .recovery_primary import (
    PRIMARY_CONFLICT_CODE,
    complete_primary,
    primary_constraints_conflict,
)


def _retain_attempts(readings, attempts):
    histories = [reading.get("auxiliary_text_attempts", []) for reading in readings]
    if any(
        not isinstance(prior, list) or any(not isinstance(a, dict) for a in prior)
        for prior in histories
    ):
        raise ValueError("Malformed original auxiliary attempt history")
    for reading, prior in zip(readings, histories, strict=True):
        additions = [attempt for attempt in attempts if attempt not in prior]
        reading["auxiliary_text_attempts"] = [*prior, *copy.deepcopy(additions)]


def refine_source_text(
    page, bounds, readings, *, maximum_rows=8, allow_chunks=False, maximum_row_height=12
):
    """Keep failures in the same raw source; only a full paired proof can refine."""
    if len(readings) != 2:
        raise ValueError("Original text recovery requires both primary views")
    if all(
        complete_primary(p, d, maximum_row_height=maximum_row_height)
        for p, d in zip(readings, (400, 600))
    ):
        return readings
    if primary_constraints_conflict(readings):
        _retain_attempts(
            readings, [{"status": "not_attempted", "code": PRIMARY_CONFLICT_CODE}]
        )
        return readings
    auxiliary = get_auxiliary_text_runtime()
    if auxiliary is None:
        return readings
    from patent_sar_extractor.core.cell_raster import original_reading_image

    images = tuple(
        original_reading_image(page, bounds, dpi, primary)
        for primary, dpi in zip(readings, (400, 600), strict=True)
    )
    attempts = []
    selected = refine_text_pair(
        images,
        readings,
        auxiliary,
        evidence_sink=attempts,
        maximum_rows=maximum_rows,
        allow_chunks=allow_chunks,
        maximum_row_height=maximum_row_height,
    )
    if selected is not None:
        return list(selected)
    if attempts:
        _retain_attempts(readings, attempts)
    return readings
