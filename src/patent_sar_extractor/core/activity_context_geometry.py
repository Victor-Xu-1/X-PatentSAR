"""Physical context windows in the existing source inventory, never inference."""

import math
from collections.abc import Mapping
from itertools import pairwise

MAX_TABLES = 4096


def valid_box(box):
    return (
        isinstance(box, (list, tuple))
        and len(box) == 4
        and all(
            type(value) in {int, float}
            and math.isfinite(value)
            and 0 <= value <= 100000
            for value in box
        )
        and box[0] < box[2]
        and box[1] < box[3]
    )


def grid_axes(region):
    return {name: list(region[name]) for name in ("xs", "ys")}


def grid_box(region):
    return [region["xs"][0], region["ys"][0], region["xs"][-1], region["ys"][-1]]


def validate_grid_axes(axes, box):
    if not isinstance(axes, Mapping) or set(axes) != {"xs", "ys"}:
        raise ValueError("Malformed original grid axes")
    for name, maximum in (("xs", 501), ("ys", 25001)):
        values = axes[name]
        if (
            not isinstance(values, list)
            or not 2 <= len(values) <= maximum
            or any(
                type(v) not in {int, float}
                or not math.isfinite(v)
                or not 0 <= v <= 100000
                for v in values
            )
            or any(b <= a for a, b in pairwise(values))
        ):
            raise ValueError("Malformed original grid axes")
    if grid_box(axes) != box or not valid_box(box):
        raise ValueError("Original grid axes do not own their bounds")


def validate_context_geometry(geometry, box):
    if (
        not isinstance(geometry, Mapping)
        or set(geometry) != {"table_bbox", "tables"}
        or geometry["table_bbox"] != box
        or not valid_box(box)
        or not isinstance(geometry["tables"], list)
        or not 1 <= len(geometry["tables"]) <= 2
        or any(not valid_box(item) for item in geometry["tables"])
        or len({tuple(item) for item in geometry["tables"]}) != len(geometry["tables"])
        or box not in geometry["tables"]
    ):
        raise ValueError("Malformed original table context geometry")


def window_tables(box, boxes):
    """Only the nearest overlapping physical barrier can change this window."""
    if (
        not valid_box(box)
        or not isinstance(boxes, (list, tuple, set))
        or not 1 <= len(boxes) <= MAX_TABLES
        or any(not valid_box(item) for item in boxes)
        or tuple(box) not in {tuple(item) for item in boxes}
    ):
        raise ValueError("Original context grid inventory exceeds its bounds")
    prior = [
        item
        for item in boxes
        if max(0, box[1] - 310) < item[3] <= box[1]
        and min(item[2], box[2]) > max(item[0], box[0])
    ]
    if not prior:
        return [list(box)]
    bottom = max(item[3] for item in prior)
    # Ties have the same boundary. Literal coordinate order is deterministic;
    # it never chooses a scientific condition or molecule mapping.
    barrier = min(tuple(item) for item in prior if item[3] == bottom)
    return [list(box), list(barrier)]


def context_region(region, boxes):
    box = grid_box(region)
    geometry = {"table_bbox": box, "tables": window_tables(box, boxes)}
    validate_context_geometry(geometry, geometry["table_bbox"])
    return {**region, "context_geometry": geometry}


def context_floor(geometry):
    box = geometry["table_bbox"]
    validate_context_geometry(geometry, box)
    floor = max(0, box[1] - 310)
    for other in geometry["tables"]:
        if other[3] <= box[1] and min(other[2], box[2]) > max(other[0], box[0]):
            floor = max(floor, other[3])
    return floor


def validate_context_inventory(regions):
    """Context blockers must be recorded physical grids, not invented boxes."""
    pages = {}
    for record in regions:
        if "grid_axes" in record:
            validate_grid_axes(record["grid_axes"], record["bbox"])
            pages.setdefault(record["page_no"], set()).add(tuple(record["bbox"]))
    for record in regions:
        geometry = (record.get("layout") or {}).get("context_geometry")
        if geometry is None:
            continue
        validate_context_geometry(geometry, record["bbox"])
        expected = window_tables(record["bbox"], pages.get(record["page_no"], set()))
        if geometry["tables"] != expected:
            raise ValueError(
                "Original context window differs from its physical grid inventory"
            )


def validate_header_context_geometry(proof, regions):
    """Saved header windows must name the same recorded original grid inventory."""
    source = proof.get("original_source")
    if not isinstance(source, dict) or source.get("schema_version") != 2:
        return
    geometry, page = source.get("context_geometry"), proof.get("page_no")
    box = proof.get("table_bbox")
    validate_context_geometry(geometry, box)
    if type(page) is not int or not isinstance(regions, list) or len(regions) > 25000:
        raise ValueError("Missing original physical context inventory")
    known = set()
    for record in regions:
        if record.get("page_no") == page and "grid_axes" in record:
            validate_grid_axes(record["grid_axes"], record.get("bbox"))
            known.add(tuple(record["bbox"]))
    if geometry["tables"] != window_tables(box, known):
        raise ValueError(
            "Header context window differs from its physical grid inventory"
        )
