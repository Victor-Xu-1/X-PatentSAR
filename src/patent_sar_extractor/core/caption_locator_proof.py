"""A location nomination can name its proved cell, never a new identifier."""

import math

from .heading_cell_source import valid_cell_geometry
from .heading_source_geometry import MAX_HEADING_HEIGHT
from .printed_identifiers import identifier_key
from .source_cell_pixels import closed_cell_masks
from .source_section_roles import heading_members, section_heading


def locator_candidate(line):
    if not isinstance(line, dict) or not isinstance(line.get("text"), str):
        return False
    observed = section_heading(line.get("text"))
    return bool(
        line.get("source") == "page_ocr"
        and line.get("geometry_space") == "rendered"
        and identifier_key(line.get("text"), wrapped=True, terminal_period=True)
        and observed
        and observed["role"] == "compound_heading"
        and len(heading_members(observed)) == 1
    )


def valid_locator_scope(packet, line, size):
    if (
        not locator_candidate(line)
        or not isinstance(size, list)
        or len(size) != 2
        or any(
            type(v) not in (int, float) or not math.isfinite(v) or not 0 < v <= 100000
            for v in size
        )
        or not valid_cell_geometry(packet, line.get("bbox"), size, MAX_HEADING_HEIGHT)
    ):
        return False
    return closed_cell_masks(packet["pixels"], packet["cell"], size) is not None
