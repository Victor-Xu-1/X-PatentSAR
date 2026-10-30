"""Capture/replay original context paint and physical rulings without OCR."""

from .native_window_coverage import observe_native_window
from .source_cell_pixels import observe_closed_cell
from .source_geometry import SourceTokens, source_layout
from .source_observations import source_cell_observation
from .source_paint_visibility import native_paint_view
from .title_context_grids import (
    context_ruling_cells,
    title_ruling_budget,
)
from .title_ink_geometry import title_ink_rows
from .title_raster_source import observe_title_raster


def observe_title_ink(
    page, bounds, context, *, layout=None, paint_view=None, version=5
):
    if type(version) is not int or version not in {4, 5}:
        raise ValueError("Unknown original title-ink version")
    layout = source_layout(page) if layout is None else layout
    size = [page.rect.width, page.rect.height]
    cells = context_ruling_cells(context, bounds, boundary_contacts=version == 5)
    within_budget = title_ruling_budget(
        cells, size, bounds=bounds if version == 5 else None
    )
    from .boundary_cell_pixels import observe_boundary_cell

    window = observe_native_window(page, bounds, paint_view=paint_view)
    return {
        "version": version,
        "page_no": page.number + 1,
        "page_size": size,
        "bbox": list(bounds),
        "context": context,
        "native_source": source_cell_observation(
            SourceTokens(layout.native, layout), bounds, native=True
        ),
        "native_window": window,
        "raster_source": observe_title_raster(page, bounds)
        if within_budget
        and window["refusal"] is None
        and any(p["kind"] == "fill-image" for p in window["paints"])
        else None,
        "ruling_sources": [
            {
                "cell": cell,
                "pixels": (
                    observe_boundary_cell(page, cell)
                    if version == 5 and cell[3] <= bounds[1]
                    else observe_closed_cell(page, cell)
                )
                if within_budget
                else None,
            }
            for cell in cells
        ],
    }


def replay_title_ink(page, source, *, layout=None, paint_view=None):
    if (
        title_ink_rows(source) is None
        or source["page_no"] != page.number + 1
        or source["page_size"] != [page.rect.width, page.rect.height]
    ):
        raise ValueError("Invalid original title-ink inventory")
    view = native_paint_view(page) if paint_view is None else paint_view
    actual = observe_title_ink(
        page,
        source["bbox"],
        source["context"],
        layout=layout,
        paint_view=view,
        version=source["version"],
    )
    if actual != source:
        raise ValueError("Original title-ink inventory differs")
