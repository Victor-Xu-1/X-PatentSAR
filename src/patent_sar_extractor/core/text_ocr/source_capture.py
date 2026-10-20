"""Shared unresolved-only original text capture, without scientific decisions."""

from .cell_capture import refine_text_pair
from .configuration import get_auxiliary_text_runtime
from .recovery_primary import complete_primary


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
        for reading in readings:
            reading["auxiliary_text_attempts"] = attempts
    return readings
