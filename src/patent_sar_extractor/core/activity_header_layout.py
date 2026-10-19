"""Bounded missing-header role discovery, never the final field/value reader."""

import math
from dataclasses import dataclass
from itertools import pairwise

from .activity_context_geometry import context_floor
from .activity_grid_context import _prefix, table_matrix
from .activity_header_columns import observe_header_columns
from .activity_header_identity import schema_requires_review
from .activity_header_layout_proof import (
    agreed_layout,
    known_discovery_conflict,
    valid_physical_discovery,
)
from .activity_header_pair import observe_header_pair
from .activity_headers import context_from_text, grid_schema
from .activity_models import GridSchema
from .table_geometry import ocr_tokens_with_positions
from .text_ocr import configuration


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
    floor = (
        context_floor(region["context_geometry"]) if "context_geometry" in region else 0
    )
    return limit, (0, max(0, floor, ys[0] - 80), page.rect.width, ys[limit])


def discover_header_layout(page, region, bounds, limit, *, tokens=()) -> HeaderLayout:
    """Two original clips prove the same ID columns and physical row boundary.

    A bounded first-three-row clip can contain initial values as locator hints;
    it never publishes those values or final field proof. All final fields are
    reread through the single column adapter after this discovery.
    """
    candidates, observations = [], []
    for dpi in (400, 600):
        observed_tokens = ocr_tokens_with_positions(page, dpi=dpi, bounds=bounds)
        matrix, prefix = (
            table_matrix(observed_tokens, region),
            _prefix(observed_tokens, region),
        )
        candidate = grid_schema(context_from_text(prefix, prefix), matrix)
        observations.append(
            {
                "method": f"header_layout_{dpi}dpi",
                "bbox": list(bounds),
                "matrix": matrix[: candidate.first_data_row if candidate else limit],
                "prefix": prefix,
            }
        )
        candidates.append(candidate)
    selected = agreed_layout(candidates, len(region["xs"]) - 1, limit)
    if selected is not None and not schema_requires_review(selected):
        return HeaderLayout(selected, tuple(observations))
    if configuration.get_auxiliary_text_runtime() is None:
        return HeaderLayout(selected, tuple(observations))
    return _physical_layout(page, region, limit, tokens, selected, observations)


def _physical_layout(page, region, limit, tokens, prior, observations):
    """One bounded first-three-row locator, never a body-value producer."""
    if type(limit) is not int or not 1 <= limit <= 3:
        return HeaderLayout(prior, tuple(observations))
    rows = [[], []]
    axes = {"xs": list(region["xs"]), "ys": list(region["ys"][: limit + 1])}
    for index in range(limit):
        row_region = {"xs": axes["xs"], "ys": axes["ys"][index : index + 2]}
        pair = observe_header_pair(page, row_region, 1, tokens, observe_header_columns)
        for view, columns in enumerate(pair):
            rows[view].append(
                {
                    "bbox": [
                        axes["xs"][0],
                        row_region["ys"][0],
                        axes["xs"][-1],
                        row_region["ys"][1],
                    ],
                    "columns": list(columns.columns),
                }
            )
    physical = [
        {
            "method": f"physical_header_layout_{dpi}dpi",
            "grid_axes": axes,
            "bbox": [axes["xs"][0], axes["ys"][0], axes["xs"][-1], axes["ys"][-1]],
            "prefix": observed["prefix"],
            "rows": read_rows,
            "matrix": [[c["raw_text"] for c in row["columns"]] for row in read_rows],
        }
        for dpi, observed, read_rows in zip((400, 600), observations, rows)
    ]
    candidates = [
        grid_schema(context_from_text(o["prefix"], o["prefix"]), o["matrix"])
        for o in physical
    ]
    selected = agreed_layout(candidates, len(axes["xs"]) - 1, limit)
    combined = [*observations, *physical]
    if selected is not None and not known_discovery_conflict(observations, selected):
        from .activity_header_proof import valid_header_column

        proof = {
            "discovery_observations": combined,
            "header_band_bbox": [
                axes["xs"][0],
                axes["ys"][0],
                axes["xs"][-1],
                axes["ys"][selected.first_data_row],
            ],
        }
        if valid_physical_discovery(proof, valid_header_column):
            return HeaderLayout(selected, tuple(combined))
    return HeaderLayout(prior, tuple(combined))
