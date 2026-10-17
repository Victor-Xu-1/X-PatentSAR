"""Quantitative-figure references in the existing heading/source ledger.

No plotted values, chemical identities or molecules are generated here. A failed
role observation remains an unproved heading; ordinary headings stay unchanged.
"""

import re

from .activity_grid_role_observation import observe_role_cells
from .cell_frame_proof import inside_box
from .plot_reference_axes import observe_axes, valid_axes
from .plot_reference_geometry import (
    context_bounds,
    figure_caption,
    legend_heading,
    literal,
    literal_bounds,
    marker_bounds,
    plot_axes,
    source_literal,
)
from .plot_reference_marker import observe_marker, valid_marker
from .source_geometry import SourceTokens, source_layout
from .source_observations import project_source_observation, source_observation_status
from .source_section_roles import section_heading
from .source_window_chunks import (
    observe_source_window,
    observe_window_sources,
    source_packet_projection,
    validate_source_window,
    window_source_tokens,
)
from .table_geometry import page_tokens
from .unruled_header_readings import original_header_readings

ROLE = "figure_label_reference"


def _parts(figure, nomination):
    return [figure["caption"], *figure["axes"]["x"], *figure["axes"]["y"], nomination]


def _confirmed(figure, hint, size):
    if not isinstance(figure, dict) or set(figure) != {
        "caption",
        "axes",
        "window",
        "chunks",
        "literal_cells",
        "marker",
        "axis_strokes",
    }:
        return False
    caption, axes, window = figure["caption"], figure["axes"], figure["window"]
    if (
        not isinstance(caption, dict)
        or set(caption) != {"text", "bbox"}
        or not figure_caption(caption.get("text"))
        or not isinstance(axes, dict)
        or set(axes) != {"x", "y"}
        or any(
            not isinstance(group, list) or not 3 <= len(group) <= 32
            for group in axes.values()
        )
    ):
        return False
    parts = _parts(figure, hint)
    if any(
        set(part) != {"text", "bbox"}
        for group in axes.values()
        for part in group
        if isinstance(part, dict)
    ):
        return False
    if any(
        not isinstance(p, dict)
        or not isinstance(p.get("text"), str)
        or len(p["text"]) > 4096
        or not inside_box(p.get("bbox"), [0, 0, *size])
        for p in parts
    ):
        return False
    if window != context_bounds(caption, axes, hint["bbox"], size):
        return False
    validate_source_window(figure["chunks"], window)
    tokens = window_source_tokens(figure["chunks"], window)
    if plot_axes(tokens, caption, hint["bbox"], size) != axes:
        return False
    if not valid_marker(figure["marker"], hint["bbox"], size):
        return False
    if not valid_axes(figure["axis_strokes"], axes, size):
        return False
    key_box = marker_bounds(hint["bbox"], size)
    if any(
        key_box[0] <= p["x"] < key_box[2]
        and key_box[1] <= p["y"] < key_box[3]
        and p["text"].strip()
        for p in [*tokens, *window_source_tokens(figure["chunks"], window, native=True)]
    ):
        return False
    cells = figure["literal_cells"]
    if not isinstance(cells, list) or len(cells) != len(parts):
        return False
    for part, cell in zip(parts, cells):
        if not isinstance(cell, dict) or set(cell) != {"bbox", "sources", "reading"}:
            return False
        box = literal_bounds(part["bbox"], size)
        if (
            cell["bbox"] != box
            or not isinstance(cell["sources"], list)
            or not 1 <= len(cell["sources"]) <= 2
        ):
            return False
        for packet in cell["sources"]:
            if source_observation_status(
                packet, box, packet.get("text")
            ) == "invalid" or not source_packet_projection(
                packet, figure["chunks"], box
            ):
                return False
        values = original_header_readings(
            cell["reading"],
            [box[0], box[2]],
            [box[1], box[3]],
            cell["sources"],
            identity=literal,
        )
        if values is None or literal(values[0]) != literal(part["text"]):
            return False
        parents = [
            chunk for chunk in figure["chunks"] if inside_box(box, chunk["bbox"])
        ]
        if len(parents) != 1:
            return False
        # The complete parent stays authoritative even if a projected carrier
        # drops an origin. Neither native nor raster contradictions disappear.
        for original in parents[0]["sources"]:
            retained = project_source_observation(original, box)
            if (
                retained["status"] == "qualified"
                and retained["text"].strip()
                and literal(retained["text"]) != literal(values[0])
            ):
                return False
    return True


def plot_reference_status(proof):
    if not isinstance(proof, dict) or set(proof) != {
        "version",
        "original_pdf_sha256",
        "page_no",
        "page_size",
        "bbox",
        "nomination",
        "figure_source",
        "status",
    }:
        return "invalid", None
    size, hint = proof["page_size"], proof["nomination"]
    if (
        type(proof["version"]) is not int
        or proof["version"] != 2
        or not isinstance(proof["original_pdf_sha256"], str)
        or not re.fullmatch(r"[a-f0-9]{64}", proof["original_pdf_sha256"])
        or type(proof["page_no"]) is not int
        or not 1 <= proof["page_no"] <= 20000
        or not isinstance(size, list)
        or len(size) != 2
        or any(type(v) not in {int, float} or not 0 < v <= 100000 for v in size)
        or not isinstance(hint, dict)
        or set(hint) != {"text", "source", "bbox", "geometry_space"}
        or hint["source"] not in {"native", "page_ocr"}
        or hint["geometry_space"] != "rendered"
        or not isinstance(hint["text"], str)
        or len(hint["text"]) > 4096
        or proof["bbox"] != hint["bbox"]
        or not inside_box(hint["bbox"], [0, 0, *size])
        or not legend_heading(hint["text"])
    ):
        return "invalid", None
    try:
        confirmed = _confirmed(proof["figure_source"], hint, size)
    except (KeyError, ValueError, TypeError, AttributeError, IndexError):
        confirmed = False
    declaration = {**section_heading(hint["text"]), "role": ROLE}
    return ("confirmed", declaration) if confirmed else ("unresolved", None)


def observe_plot_reference(
    page, line, lines, original_sha, *, cache, tokens_for_page=None
):
    """Nominate from existing page facts, then use the one physical-cell SDK."""
    if line.get("geometry_space") != "rendered" or not legend_heading(line["text"]):
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
    options = [
        (caption, axes)
        for caption in captions.values()
        if (axes := plot_axes(tokens, caption, line["bbox"], size)) is not None
    ]
    if len(options) != 1:
        return None
    marker = observe_marker(page, line["bbox"], size)
    if marker is None:
        return None
    caption, axes = options[0]
    strokes = observe_axes(page, axes, size)
    if strokes is None:
        return None
    window = context_bounds(caption, axes, line["bbox"], size)
    figure = {
        "caption": caption,
        "axes": axes,
        "window": window,
        "chunks": observe_source_window(tokens, window),
        "literal_cells": [],
        "marker": marker,
        "axis_strokes": strokes,
    }
    for part in _parts(figure, line):
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
        "version": 2,
        "original_pdf_sha256": original_sha,
        "page_no": page.number + 1,
        "page_size": size,
        "bbox": list(line["bbox"]),
        "nomination": {
            k: line[k] for k in ("text", "source", "bbox", "geometry_space")
        },
        "figure_source": figure,
        "status": "unresolved",
    }
    proof["status"], _ = plot_reference_status(proof)
    return proof
