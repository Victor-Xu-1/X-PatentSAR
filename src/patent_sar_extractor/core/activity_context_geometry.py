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
        or set(geometry) - {"parallel_span"} != {"table_bbox", "tables"}
        or geometry["table_bbox"] != box
        or not valid_box(box)
        or not isinstance(geometry["tables"], list)
        or not 1 <= len(geometry["tables"]) <= 4
        or any(not valid_box(item) for item in geometry["tables"])
        or len({tuple(item) for item in geometry["tables"]}) != len(geometry["tables"])
        or box not in geometry["tables"]
    ):
        raise ValueError("Malformed original table context geometry")
    if "parallel_span" in geometry:
        span = geometry["parallel_span"]
        if (
            not isinstance(span, list)
            or len(span) != 2
            or any(
                type(value) not in {int, float}
                or not math.isfinite(value)
                or not 0 <= value <= 100000
                for value in span
            )
            or not span[0] <= box[0] < box[2] <= span[1]
        ):
            raise ValueError("Malformed original parallel context span")


def _windows_overlap(a, b):
    return min(a[3], b[3]) > max(max(0, a[1] - 310), max(0, b[1] - 310))


def parallel_span(box, boxes):
    """A caption candidate span; exact header carry remains a separate gate."""
    aligned = [
        item
        for item in boxes
        if abs(item[1] - box[1]) <= 4
        and abs((item[2] - item[0]) - (box[2] - box[0])) <= 4
        and (
            item == box
            or tuple(item) == tuple(box)
            or item[2] <= box[0]
            or item[0] >= box[2]
        )
    ]
    return [min(item[0] for item in aligned), max(item[2] for item in aligned)]


def window_tables(box, boxes):
    """Keep only the nearest upper/left/right physical window boundaries."""
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
    output = [list(box)]
    if prior:
        bottom = max(item[3] for item in prior)
        # Ties share a boundary; coordinate order never chooses scientific fields.
        output.append(list(min(tuple(item) for item in prior if item[3] == bottom)))
    parallel = [item for item in boxes if _windows_overlap(item, box)]
    left = [item for item in parallel if item[2] <= box[0]]
    right = [item for item in parallel if item[0] >= box[2]]
    if left:
        output.append(list(min(left, key=lambda item: (-item[2], tuple(item)))))
    if right:
        output.append(list(min(right, key=lambda item: (item[0], tuple(item)))))
    return output


def context_region(region, boxes):
    box = grid_box(region)
    geometry = {
        "table_bbox": box,
        "tables": window_tables(box, boxes),
        "parallel_span": parallel_span(box, boxes),
    }
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


def context_band(geometry):
    """Neighbouring grids divide columns; no assay text determines ownership."""
    box = geometry["table_bbox"]
    validate_context_geometry(geometry, box)
    left, right = 0, 100000
    for other in geometry["tables"]:
        if not _windows_overlap(other, box):
            continue
        if other[2] <= box[0]:
            left = max(left, (other[2] + box[0]) / 2)
        if other[0] >= box[2]:
            right = min(right, (other[0] + box[2]) / 2)
    return left, right


def validate_context_inventory(regions, *, current=False):
    """Context blockers must be recorded physical grids, not invented boxes."""
    pages, roots = {}, {}
    for record in regions:
        if (
            current
            and record["kind"] == "grid"
            and not any(
                key in record for key in ("grid_axes", "parent_grid", "column_scope")
            )
        ):
            raise ValueError("Missing current original physical grid inventory")
        if "grid_axes" in record:
            validate_grid_axes(record["grid_axes"], record["bbox"])
            pages.setdefault(record["page_no"], set()).add(tuple(record["bbox"]))
            key = record["page_no"], tuple(record["bbox"])
            if key in roots and roots[key][0] != record["grid_axes"]:
                raise ValueError("Conflicting original parent grid axes")
            if key not in roots:
                axes = record["grid_axes"]
                roots[key] = (
                    axes,
                    frozenset(axes["xs"]),
                    frozenset(pairwise(axes["ys"])),
                )
    for record in regions:
        if "parent_grid" in record:
            parent = roots.get((record["page_no"], tuple(record["parent_grid"])))
            child = record["bbox"]
            if (
                parent is None
                or child[0] not in parent[1]
                or child[2] not in parent[1]
                or (child[1], child[3]) not in parent[2]
            ):
                raise ValueError("Unresolved original row has no exact physical parent")
        if "column_scope" in record:
            scope = record["column_scope"]
            parent = roots.get((record["page_no"], tuple(scope["parent_grid"])))
            column, header = scope["column"], scope["header_row"]
            if parent is None or not (
                column + 1 < len(parent[0]["xs"])
                and header + 1 < len(parent[0]["ys"])
                and record["bbox"]
                == [
                    parent[0]["xs"][column],
                    parent[0]["ys"][header],
                    parent[0]["xs"][column + 1],
                    parent[0]["ys"][-1],
                ]
            ):
                raise ValueError(
                    "Unresolved original column has no exact physical parent"
                )
        geometry = (record.get("layout") or {}).get("context_geometry")
        if (
            current
            and record.get("layout") is not None
            and (geometry is None or "parallel_span" not in geometry)
        ):
            raise ValueError("Missing current original context geometry")
        if geometry is None:
            continue
        validate_context_geometry(geometry, record["bbox"])
        expected = window_tables(record["bbox"], pages.get(record["page_no"], set()))
        if geometry["tables"] != expected:
            raise ValueError(
                "Original context window differs from its physical grid inventory"
            )
        if "parallel_span" in geometry and geometry["parallel_span"] != parallel_span(
            record["bbox"], pages[record["page_no"]]
        ):
            raise ValueError(
                "Original parallel span differs from its physical grid inventory"
            )


def validate_header_context_geometry(proof, regions):
    """Saved header windows must name the same recorded original grid inventory."""
    source = proof.get("original_source")
    if not isinstance(source, dict) or source.get("schema_version") not in {2, 3}:
        return
    geometry, page = source.get("context_geometry"), proof.get("page_no")
    box = proof.get("table_bbox")
    validate_context_geometry(geometry, box)
    if source["schema_version"] == 3 and "parallel_span" not in geometry:
        raise ValueError("Missing current original parallel context span")
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
    if "parallel_span" in geometry and geometry["parallel_span"] != parallel_span(
        box, known
    ):
        raise ValueError(
            "Header parallel span differs from its physical grid inventory"
        )
