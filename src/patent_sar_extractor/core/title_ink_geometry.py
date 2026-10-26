"""Bounded physical title rows from original paint, not recognized-word boxes."""

from itertools import pairwise

from .activity_context_geometry import (
    context_band,
    context_floor,
    validate_context_geometry,
    validate_grid_axes,
)
from .cell_frame_proof import inside_box
from .cell_raster import cell_pixel_rect
from .cell_text_limits import PHYSICAL_ROW_GAP
from .heading_source_geometry import MAX_HEADING_HEIGHT, MAX_HEADING_ROWS
from .heading_title_geometry import original_row_marks
from .native_window_coverage import (
    MAX_WINDOW_PAINTS,
    native_window_text_complete,
    valid_native_window,
)
from .source_cell_pixels import MAX_CELL_PIXELS, closed_cell_masks, source_window
from .source_observations import source_observation_status


def title_context_spec(*, geometry=None, logical_window=None, grid_axes=None):
    return {
        "geometry": geometry,
        "logical_window": logical_window,
        "grid_axes": grid_axes,
    }


def context_ruling_cells(context, bounds):
    """Only the trusted caller's first physical row can supply boundary rules."""
    if not isinstance(context, dict) or set(context) != {
        "geometry",
        "logical_window",
        "grid_axes",
    }:
        raise ValueError("Malformed original title discovery context")
    geometry, logical, axes = (
        context[name] for name in ("geometry", "logical_window", "grid_axes")
    )
    if geometry is not None:
        if logical is not None:
            raise ValueError("Mixed physical and logical title contexts")
        validate_context_geometry(geometry, geometry.get("table_bbox"))
        box = geometry["table_bbox"]
        if bounds != [0, context_floor(geometry), bounds[2], box[1]]:
            raise ValueError("Title discovery leaves its original context")
    elif logical is not None:
        if not inside_box(logical, [0, 0, bounds[2], 100000]):
            raise ValueError("Invalid original logical title context")
        if bounds != [0, max(0, logical[1] - 310), bounds[2], logical[1]]:
            raise ValueError("Title discovery leaves its logical context")
    if axes is None:
        return []
    if geometry is None:
        raise ValueError("Title ruling needs original physical grid ownership")
    validate_grid_axes(axes, geometry["table_bbox"])
    xs, ys = axes["xs"], axes["ys"]
    return [[left, ys[0], right, ys[1]] for left, right in pairwise(xs)]


def title_ruling_budget(cells, size):
    return (
        sum(
            rectangle.width * rectangle.height
            for cell in cells
            for rectangle in (cell_pixel_rect(source_window(cell, size), 600),)
        )
        <= MAX_CELL_PIXELS
    )


def caption_title_context(scope):
    return title_context_spec(
        geometry=scope["context_geometry"], grid_axes=scope["grid_axes"]
    )


def title_ink_rows(source):
    """Return all physical rows and explicit refusal; never a successful prefix.

    A row requiring text reading includes its same-row native words. Complete
    native rows stay on the existing no-model path. Unknown paint may neither
    disappear as whitespace nor choose an owner among parallel catalogues.
    """
    if (
        not isinstance(source, dict)
        or set(source)
        != {
            "version",
            "page_no",
            "page_size",
            "bbox",
            "context",
            "native_source",
            "native_window",
            "ruling_sources",
        }
        or type(source["version"]) is not int
        or source["version"] != 1
    ):
        return None
    native, window, bounds, size = (
        source[name] for name in ("native_source", "native_window", "bbox", "page_size")
    )
    if (
        type(source["page_no"]) is not int
        or not 1 <= source["page_no"] <= 20000
        or not valid_native_window(window, bounds)
        or window["page_size"] != size
        or not isinstance(native, dict)
        or native.get("origin") != "native"
        or source_observation_status(native, bounds, native.get("text")) == "invalid"
    ):
        return None
    try:
        cells = context_ruling_cells(source["context"], bounds)
    except (ValueError, TypeError, KeyError, AttributeError, IndexError):
        return None
    rulings = source["ruling_sources"]
    if not isinstance(rulings, list) or len(rulings) != len(cells):
        return None
    if not title_ruling_budget(cells, size):
        return (
            ([], "title_ruling_budget")
            if all(
                isinstance(ruling, dict)
                and set(ruling) == {"cell", "pixels"}
                and ruling["cell"] == cell
                and ruling["pixels"] is None
                for cell, ruling in zip(cells, rulings, strict=True)
            )
            else None
        )
    proved = []
    for cell, ruling in zip(cells, rulings, strict=True):
        if (
            not isinstance(ruling, dict)
            or set(ruling) != {"cell", "pixels"}
            or ruling["cell"] != cell
        ):
            return None
        if ruling["pixels"] is not None:
            if closed_cell_masks(ruling["pixels"], cell, size) is None:
                return None
            proved.append(cell)
    if window["refusal"] is not None:
        return [], window["refusal"]
    if (
        native["boundary_tokens"]
        or (native["tokens"] and not native_window_text_complete(window, native))
        or (
            not native["tokens"]
            and any(p["kind"] == "fill-text" for p in window["paints"])
        )
    ):
        return [], "incomplete_native_title_context"
    geometry = source["context"]["geometry"]
    if geometry is not None and context_band(geometry) != (0, 100000):
        return [], "ambiguous_title_columns"
    marks = original_row_marks(
        {"native_source": native, "window": window}, ruling_cells=proved
    )
    if len(marks) > MAX_WINDOW_PAINTS:
        return [], "source_mark_budget"
    if any(not inside_box(mark, bounds) for mark in marks):
        return [], "crossing_title_context_ink"
    groups = []
    bottom = None
    for box in sorted(marks, key=lambda item: (item[1], item[0], item[3])):
        if bottom is not None and box[1] <= bottom + PHYSICAL_ROW_GAP:
            groups[-1].append(box)
            bottom = max(bottom, box[3])
        else:
            groups.append([box])
            bottom = box[3]
    native_boxes = {tuple(token["bbox"]) for token in native["tokens"]}
    rows = [
        {
            "bbox": [
                min(b[0] for b in group),
                min(b[1] for b in group),
                max(b[2] for b in group),
                max(b[3] for b in group),
            ],
            "requires_read": any(tuple(box) not in native_boxes for box in group),
        }
        for group in groups
    ]
    unknown = [row for row in rows if row["requires_read"]]
    if len(unknown) > MAX_HEADING_ROWS:
        return [], "title_row_budget"
    if any(row["bbox"][3] - row["bbox"][1] > MAX_HEADING_HEIGHT for row in unknown):
        return [], "title_height_budget"
    return rows, None
