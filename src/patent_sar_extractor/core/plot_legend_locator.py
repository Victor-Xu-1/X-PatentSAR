"""Literal graphic-key/heading locators from complete original line pixels.

An OCR prefix nominates observation only. Every physical row and literal source
survives; neither text trimming nor the first matching row establishes a role.
"""

import re

from .cell_frame_proof import inside_box
from .plot_legend_geometry import MAX_LOCATOR_PIXELS, locator_bounds, locator_rows
from .plot_literal_cells import literal_cell_text, observe_literal_cell
from .plot_reference_geometry import legend_heading, literal, literal_bounds
from .plot_reference_pixels import observe_pixels
from .source_section_roles import section_heading

_LABEL = re.compile(
    r"(?<!\w)(?:Compound|Cmpd|Cpd|化合物)(?=\s|[-:.：]|\d)", re.IGNORECASE
)
_LINE_FIELDS = {"text", "bbox", "source", "geometry_space"}


def legend_candidate(text):
    if not isinstance(text, str) or len(text) > 4096:
        return None
    if section_heading(text) is not None and not legend_heading(text):
        return None  # A known preparation/assay role is never erased as a prefix.
    matches = list(_LABEL.finditer(text))
    if len(matches) != 1:
        return None  # A second actual identifier is not discarded as a key.
    start, end = matches[0].start(), len(text.rstrip())
    return (start, end, text[start:end]) if legend_heading(text[start:end]) else None


def _locator_rows(packet, size, *, chunks=None):
    if not isinstance(packet, dict) or type(packet.get("version")) is not int:
        return None
    version = packet["version"]
    if version not in {1, 2} or set(packet) != {
        "version",
        "source_line",
        "literal_range",
        "pixels",
    } | ({"rows"} if version == 2 else set()):
        return None
    line = packet["source_line"]
    if (
        not isinstance(line, dict)
        or set(line) != _LINE_FIELDS
        or line["source"] not in {"native", "page_ocr"}
        or line["geometry_space"] != "rendered"
        or not inside_box(line["bbox"], [0, 0, *size])
        or line["bbox"][3] - line["bbox"][1] > 32
    ):
        return None
    candidate = legend_candidate(line["text"])
    if candidate is None or (
        not isinstance(packet["literal_range"], list)
        or len(packet["literal_range"]) != 2
        or any(type(v) is not int for v in packet["literal_range"])
        or packet["literal_range"] != list(candidate[:2])
    ):
        return None
    geometry = locator_rows(packet["pixels"], line, size, multiline=version == 2)
    if geometry is None:
        return None
    if version == 1:
        return [{**geometry[0], "text": candidate[2]}]
    rows = packet["rows"]
    if not isinstance(rows, list) or len(rows) != len(geometry):
        return None
    for row, part in zip(rows, geometry):
        if (
            not isinstance(row, dict)
            or set(row) != {"bbox", "key", "text", "cell"}
            or any(row[key] != part[key] for key in ("bbox", "key"))
            or not isinstance(row["text"], str)
            or not 0 < len(row["text"]) <= 4096
        ):
            return None
        text = literal_cell_text(
            row["cell"], literal_bounds(row["bbox"], size), chunks=chunks
        )
        if text is None or literal(text) != literal(row["text"]):
            return None
        if (
            section_heading(text) is not None or _LABEL.search(text)
        ) and not legend_heading(text):
            return None  # A known preparation/assay role cannot disappear.
    return rows


def locator_nomination(packet, size, *, chunks=None):
    try:
        rows = _locator_rows(packet, size, chunks=chunks)
    except (KeyError, TypeError, ValueError, AttributeError, IndexError):
        return None  # Malformed retained evidence is not an observed literal.
    if rows is None:
        return None
    candidate = legend_candidate(packet["source_line"]["text"])
    selected = [row for row in rows if literal(row["text"]) == literal(candidate[2])]
    if len(selected) != 1:
        return None
    return {
        "text": selected[0]["text"],
        "bbox": selected[0]["bbox"],
        "source": packet["source_line"]["source"],
        "geometry_space": "rendered",
    }


def observe_legend_locator(page, line, size, *, tokens=None):
    candidate = legend_candidate(line.get("text"))
    if candidate is None or not inside_box(line.get("bbox"), [0, 0, *size]):
        return None
    if line["bbox"][3] - line["bbox"][1] > 32:
        return None
    original = {key: line[key] for key in _LINE_FIELDS}
    packet = {
        "version": 2,
        "source_line": original,
        "literal_range": list(candidate[:2]),
        "pixels": observe_pixels(
            page, locator_bounds(original, size), MAX_LOCATOR_PIXELS
        ),
        "rows": [],
    }
    geometry = locator_rows(packet["pixels"], original, size, multiline=True)
    if geometry is None:
        return None
    if tokens is None:
        from .table_geometry import page_tokens

        tokens = page_tokens(page)
    for part in geometry:
        cell = observe_literal_cell(page, part, size, tokens)
        text = literal_cell_text(cell, literal_bounds(part["bbox"], size))
        if text is None:
            return None
        packet["rows"].append({**part, "text": text, "cell": cell})
    return packet if locator_nomination(packet, size) is not None else None
