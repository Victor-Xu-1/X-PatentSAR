"""Bounded original-image header rereads; no metric spelling/number guessing."""

from dataclasses import replace

from .activity_grid_context import _prefix, table_matrix
from .activity_header_metrics import normalize_metric_text
from .activity_headers import context_from_text, grid_schema
from .activity_models import GridSchema
from .table_geometry import ocr_tokens_with_positions


def refine_scanned_header(page, region: dict, original: GridSchema) -> GridSchema:
    """Require two clipped resolutions to agree on every column and caption ID.

    These are corroborating readings, not a calibrated accuracy guarantee.
    Disagreement retains the unresolved original. Values are never read here.
    """
    if page.get_text("words") or original.first_data_row <= 0:
        return original
    top, bottom = region["ys"][0], region["ys"][original.first_data_row]
    bounds = (0, max(0, top - 80), page.rect.width, bottom)
    if bottom - bounds[1] > 250:
        return original
    candidates = []
    observations = []
    for dpi in (400, 600):
        tokens = ocr_tokens_with_positions(page, dpi=dpi, bounds=bounds)
        matrix = table_matrix(tokens, region)
        prefix = _prefix(tokens, region)
        candidate = grid_schema(context_from_text(prefix, prefix), matrix)
        observations.append(
            {
                "method": f"header_ocr_{dpi}dpi",
                "bbox": list(bounds),
                "matrix": matrix[: original.first_data_row],
                "prefix": prefix,
            }
        )
        if candidate is None or candidate.first_data_row != original.first_data_row:
            return replace(
                original,
                header_resolution={
                    "status": "unresolved",
                    "observations": observations,
                },
            )
        candidates.append(candidate)
    first, second = candidates

    def compact(value):
        return "".join(normalize_metric_text(value).split()).casefold()

    agreed = [
        compact(a) == compact(b) for a, b in zip(first.raw_headers, second.raw_headers)
    ]
    headers = tuple(
        first.raw_headers[i] if ok else original.raw_headers[i]
        for i, ok in enumerate(agreed)
    )
    caption_proved = bool(first.context.table_id) and compact(
        first.context.raw_caption
    ) == compact(second.context.raw_caption)
    context = first.context if caption_proved else original.context
    selected = grid_schema(context, [list(headers)])
    if selected is None:
        return original
    return replace(
        selected,
        first_data_row=original.first_data_row,
        header_resolution={
            "status": "observed_header_consensus" if all(agreed) else "unresolved",
            "original_headers": list(original.raw_headers),
            "original_context": original.context.raw_context,
            "observations": observations,
        },
    )
