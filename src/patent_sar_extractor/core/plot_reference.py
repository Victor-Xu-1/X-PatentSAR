"""Quantitative-figure references in the existing heading/source ledger.

No plotted values, chemical identities or molecules are generated here. A failed
role observation remains an unproved heading; ordinary headings stay unchanged.
"""

from patent_sar_extractor.contracts import PLOT_REFERENCE_VERSION

from .activity_grid_role_observation import observe_role_cells
from .plot_axis_refinement import observe_reference_axes, refinement_bounds
from .plot_legend_locator import (
    legend_candidate,
    locator_nomination,
    observe_legend_locator,
)
from .plot_reference_geometry import (
    context_bounds,
    figure_caption,
    legend_heading,
    literal_bounds,
    source_literal,
)
from .plot_reference_proof import figure_parts, plot_reference_status
from .source_geometry import SourceTokens, source_layout
from .source_window_chunks import (
    observe_source_window,
    observe_window_sources,
)
from .table_geometry import page_tokens

__all__ = ["observe_plot_reference", "plot_reference_status"]


def observe_plot_reference(
    page, line, lines, original_sha, *, cache, tokens_for_page=None
):
    """Nominate from existing page facts, then use the one physical-cell SDK."""
    if (
        line.get("geometry_space") != "rendered"
        or legend_candidate(line["text"]) is None
    ):
        return None
    captions = {
        tuple(p["bbox"]): source_literal(p)
        for p in lines
        if figure_caption(p["text"]) and p.get("geometry_space") == "rendered"
    }
    if not captions or len(captions) > 64:
        return None
    if "tokens" not in cache:
        layout = source_layout(page)
        cache["tokens"] = (
            SourceTokens(list(layout.native), layout)
            if layout.native and layout.raster_bounds is None
            else tokens_for_page(page)
            if tokens_for_page
            else page_tokens(page)
        )
    tokens, size = cache["tokens"], [page.rect.width, page.rect.height]
    if not isinstance(tokens, SourceTokens):
        return None
    selected = (
        observe_reference_axes(page, tokens, list(captions.values()), line, size)
        if legend_heading(line["text"])
        else None
    )
    locator = None
    if selected is None:
        locator = observe_legend_locator(page, line, size)
        if locator is None:
            return None
        line = locator_nomination(locator, size)
        selected = observe_reference_axes(
            page, tokens, list(captions.values()), line, size
        )
    if selected is None:
        return None
    caption, axes = selected["caption"], selected["axes"]
    window = context_bounds(
        caption,
        axes,
        line["bbox"],
        size,
        row_bounds=refinement_bounds(selected, size),
        locator_bounds=locator["pixels"]["bbox"] if locator is not None else None,
    )
    figure = {
        **selected,
        "window": window,
        "chunks": observe_source_window(tokens, window),
        "literal_cells": [],
    }
    for part in figure_parts(figure, line):
        box = literal_bounds(part["bbox"], size)
        figure["literal_cells"].append(
            {
                "bbox": box,
                "sources": observe_window_sources(tokens, box),
                "reading": observe_role_cells(
                    page,
                    {"xs": [box[0], box[2]], "ys": [box[1], box[3]]},
                    tokens,
                    retain_frames=True,
                ),
            }
        )
    proof = {
        "version": PLOT_REFERENCE_VERSION,
        "original_pdf_sha256": original_sha,
        "page_no": page.number + 1,
        "page_size": size,
        "bbox": list(line["bbox"]),
        "nomination": {
            k: line[k] for k in ("text", "source", "bbox", "geometry_space")
        },
        "figure_source": figure,
        "status": "unresolved",
        "original_locator": locator,
    }
    proof["status"], _ = plot_reference_status(proof)
    return proof
