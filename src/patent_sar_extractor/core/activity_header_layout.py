"""Bounded missing-header role discovery, never the final field/value reader."""

import math
from dataclasses import dataclass
from itertools import pairwise

from .activity_grid_context import _prefix, table_matrix
from .activity_header_identity import compact_header
from .activity_headers import context_from_text, grid_schema
from .activity_models import GridSchema
from .table_geometry import ocr_tokens_with_positions


@dataclass(frozen=True)
class HeaderLayout:
    schema: GridSchema | None
    observations: tuple[dict, ...] = ()


def header_bounds(page, region, original):
    xs, ys = region.get("xs", ()), region.get("ys", ())
    if not 2 <= len(xs) <= 65 or len(ys) < 2:
        return None
    if any(
        type(v) not in (int, float) or not math.isfinite(v)
        for values in (xs, ys)
        for v in values
    ):
        return None
    if any(b <= a for values in (xs, ys) for a, b in pairwise(values)):
        return None
    limit = original.first_data_row if original else min(3, len(ys) - 1)
    if type(limit) is not int or not 1 <= limit < len(ys):
        return None
    if (
        not 0 <= xs[0] < xs[-1] <= page.rect.width
        or not 0 <= ys[0] < ys[limit] <= page.rect.height
    ):
        return None
    if ys[limit] - max(0, ys[0] - 80) > 250:
        return None
    return limit, (0, max(0, ys[0] - 80), page.rect.width, ys[limit])


def discover_header_layout(page, region, bounds, limit) -> HeaderLayout:
    """Two original clips prove the same ID columns and physical row boundary.

    A bounded first-three-row clip can contain initial values as locator hints;
    it never publishes those values or final field proof. All final fields are
    reread through the single column adapter after this discovery.
    """
    candidates, observations = [], []
    for dpi in (400, 600):
        tokens = ocr_tokens_with_positions(page, dpi=dpi, bounds=bounds)
        matrix, prefix = table_matrix(tokens, region), _prefix(tokens, region)
        candidate = grid_schema(context_from_text(prefix, prefix), matrix)
        observations.append(
            {
                "method": f"header_layout_{dpi}dpi",
                "bbox": list(bounds),
                "matrix": matrix[: candidate.first_data_row if candidate else limit],
                "prefix": prefix,
            }
        )
        if candidate is None:
            return HeaderLayout(None, tuple(observations))
        candidates.append(candidate)
    first, second = candidates
    if (
        first.first_data_row != second.first_data_row
        or first.first_data_row > limit
        or len(first.raw_headers) != len(region["xs"]) - 1
        or tuple(g.id_column for g in first.groups)
        != tuple(g.id_column for g in second.groups)
        or tuple(map(compact_header, first.raw_headers))
        != tuple(map(compact_header, second.raw_headers))
        or not first.context.table_id
        or compact_header(first.context.raw_caption)
        != compact_header(second.context.raw_caption)
    ):
        return HeaderLayout(None, tuple(observations))
    return HeaderLayout(first, tuple(observations))
