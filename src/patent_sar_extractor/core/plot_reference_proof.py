"""Quantitative-figure references in the existing heading/source ledger.

No plotted values, chemical identities or molecules are generated here. A failed
role observation remains an unproved heading; ordinary headings stay unchanged.
"""

import re

from patent_sar_extractor.contracts import PLOT_REFERENCE_VERSION

from .cell_frame_proof import inside_box
from .plot_axis_refinement import refinement_bounds, replay_axis_tokens
from .plot_legend_locator import locator_nomination
from .plot_reference_axes import valid_axes
from .plot_reference_geometry import (
    context_bounds,
    figure_caption,
    legend_heading,
    literal,
    literal_bounds,
    marker_bounds,
    plot_axes,
)
from .plot_reference_marker import valid_marker
from .source_observations import project_source_observation, source_observation_status
from .source_section_roles import section_heading
from .source_window_chunks import (
    source_packet_projection,
    validate_source_window,
    window_source_tokens,
)
from .unruled_header_readings import original_header_readings

ROLE = "figure_label_reference"


def figure_parts(figure, nomination):
    return [
        figure["caption"],
        *(figure["axes"]["x"] if figure["axis_refinement"] is None else []),
        *figure["axes"]["y"],
        nomination,
    ]


def _confirmed(figure, hint, size, locator=None, *, version):
    if not isinstance(figure, dict) or set(figure) != {
        "caption",
        "axes",
        "window",
        "chunks",
        "literal_cells",
        "marker",
        "axis_strokes",
        "axis_refinement",
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
    parts = figure_parts(figure, hint)
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
    if window != context_bounds(
        caption,
        axes,
        hint["bbox"],
        size,
        row_bounds=refinement_bounds(figure, size),
        locator_bounds=locator["pixels"]["bbox"] if locator is not None else None,
    ):
        return False
    validate_source_window(figure["chunks"], window)
    tokens = window_source_tokens(figure["chunks"], window)
    native = window_source_tokens(figure["chunks"], window, native=True)
    projected = replay_axis_tokens(figure, tokens, native, hint, size)
    if projected is None:
        return False
    if (
        plot_axes(
            projected[0],
            caption,
            hint["bbox"],
            size,
            independent_tokens=projected[1],
        )
        != axes
    ):
        return False
    if not valid_marker(figure["marker"], hint["bbox"], size):
        return False
    refinement = figure["axis_refinement"]
    anchor = (
        {"axes": refinement["nomination"], "pixels": refinement["axis_strokes"]}
        if version == PLOT_REFERENCE_VERSION and refinement is not None
        else None
    )
    if not valid_axes(figure["axis_strokes"], axes, size, anchor=anchor):
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
    if not isinstance(proof, dict) or set(proof) != (
        {
            "version",
            "original_pdf_sha256",
            "page_no",
            "page_size",
            "bbox",
            "nomination",
            "figure_source",
            "status",
        }
        | (
            {"original_locator"}
            if proof.get("version") in (4, PLOT_REFERENCE_VERSION)
            else set()
        )
    ):
        return "invalid", None
    size, hint = proof["page_size"], proof["nomination"]
    if (
        type(proof["version"]) is not int
        or proof["version"] not in {3, 4, PLOT_REFERENCE_VERSION}
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
        locator = proof.get("original_locator")
        if (
            proof["version"] == 4
            or proof["version"] == PLOT_REFERENCE_VERSION
            and locator is not None
        ) and locator_nomination(locator, size) != hint:
            return "unresolved", None
        confirmed = _confirmed(
            proof["figure_source"], hint, size, locator, version=proof["version"]
        )
    except (KeyError, ValueError, TypeError, AttributeError, IndexError):
        confirmed = False
    declaration = {**section_heading(hint["text"]), "role": ROLE}
    return ("confirmed", declaration) if confirmed else ("unresolved", None)
