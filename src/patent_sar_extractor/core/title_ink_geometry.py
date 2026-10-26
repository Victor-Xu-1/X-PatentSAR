"""Complete original title-ink validation and physical row discovery."""

from .activity_context_geometry import context_band
from .cell_frame_proof import inside_box
from .heading_title_geometry import original_row_marks
from .native_window_coverage import (
    MAX_WINDOW_PAINTS,
    native_window_text_complete,
    valid_native_window,
)
from .source_cell_pixels import closed_cell_masks
from .source_observations import source_observation_status
from .title_context_grids import context_ruling_cells, title_ruling_budget
from .title_parallel_rows import original_title_rows


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
            "raster_source",
        }
        or type(source["version"]) is not int
        or source["version"] != 3
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
    if "parallel_grids" in source["context"] and len(proved) != len(cells):
        return [], "unproved_parallel_title_grid"
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
    if (
        geometry is not None
        and context_band(geometry) != (0, 100000)
        and "parallel_grids" not in source["context"]
    ):
        return [], "ambiguous_title_columns"
    raster = source["raster_source"]
    raster_marks = None
    images = any(p["kind"] == "fill-image" for p in window["paints"])
    if images:
        from .title_raster_source import title_raster_marks

        observed = title_raster_marks(
            raster,
            bounds,
            size,
            rulings,
            components="parallel_grids" in source["context"],
        )
        if observed is None:
            return None
        raster_marks, refusal = observed
        if refusal is not None:
            return [], refusal
    elif raster is not None:
        return None
    marks = original_row_marks(
        {"native_source": native, "window": window},
        ruling_cells=proved,
        raster_marks=raster_marks,
    )
    if len(marks) > MAX_WINDOW_PAINTS:
        return [], "source_mark_budget"
    if any(not inside_box(mark, bounds) for mark in marks):
        return [], "crossing_title_context_ink"
    return original_title_rows(marks, native, bounds, source["context"])
