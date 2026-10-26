"""One paired physical text reader shared by original title consumers."""

from dataclasses import replace

from .cell_ocr_observation import observe_cell
from .cell_raster import render_cell_raster
from .cell_text_scope import text_scope


def observe_paired_text(
    page, bounds, engine, normalize, *, maximum_rows, maximum_row_height
):
    observations, frames = [], []
    for dpi in (400, 600):
        raster = render_cell_raster(page, list(bounds), dpi, purpose="text")
        reading = observe_cell(
            raster.image,
            "heading",
            dpi,
            engine,
            normalize,
            maximum_text_rows=maximum_rows,
            maximum_row_height=maximum_row_height,
        )
        reading = replace(
            reading,
            source_frame=raster.frame,
            source_window=raster.source_window,
            text_scope=text_scope(maximum_rows, maximum_row_height),
        )
        observations.append(reading.evidence(dpi, bounds))
        frames.append(raster.frame)
    return observations, frames
