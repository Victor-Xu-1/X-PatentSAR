"""Bounded original-image header rereads; no metric spelling/number guessing."""

from dataclasses import replace

from .activity_grid_context import _prefix, table_matrix
from .activity_header_metrics import normalize_metric_text
from .activity_headers import context_from_text, grid_schema
from .activity_models import GridSchema
from .table_geometry import ocr_tokens_with_positions


def refine_scanned_header(
    page, region: dict, original: GridSchema | None
) -> GridSchema | None:
    """Require two clipped resolutions to agree on every column and caption ID.

    These are corroborating readings, not a calibrated accuracy guarantee.
    Disagreement retains the unresolved original. Values are never read here.
    """
    if page.get_text("words") or original is not None and original.first_data_row <= 0:
        return original
    limit = original.first_data_row if original else min(3, len(region["ys"]) - 1)
    top, bottom = region["ys"][0], region["ys"][limit]
    bounds = (0, max(0, top - 80), page.rect.width, bottom)
    if bottom - bounds[1] > 250 or not 2 <= len(region["xs"]) <= 65:
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
                "matrix": matrix[: candidate.first_data_row if candidate else limit],
                "prefix": prefix,
            }
        )
        if candidate is None or (
            original is not None and candidate.first_data_row != original.first_data_row
        ):
            if original is None:
                return None
            return replace(
                original,
                header_resolution={
                    "status": "unresolved",
                    "observations": observations,
                },
            )
        candidates.append(candidate)
    first, second = candidates
    if (
        first.first_data_row != second.first_data_row
        or len(first.raw_headers) != len(second.raw_headers)
        or len(first.raw_headers) != len(region["xs"]) - 1
        or tuple(g.id_column for g in first.groups)
        != tuple(g.id_column for g in second.groups)
    ):
        return original

    def compact(value):
        return "".join(normalize_metric_text(value).split()).casefold()

    agreed = [
        compact(a) == compact(b) for a, b in zip(first.raw_headers, second.raw_headers)
    ]
    caption_proved = bool(first.context.table_id) and compact(
        first.context.raw_caption
    ) == compact(second.context.raw_caption)
    # A missing schema has no safe per-column fallback. Only complete agreement
    # on the actual header, row boundary and caption can establish a new one.
    if original is None:
        if not all(agreed) or not caption_proved:
            return None
        return replace(
            first,
            header_resolution={
                "status": "observed_header_consensus",
                "original_headers": [],
                "original_context": "",
                "observations": observations,
            },
        )
    headers = tuple(
        first.raw_headers[i] if ok else original.raw_headers[i]
        for i, ok in enumerate(agreed)
    )
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
