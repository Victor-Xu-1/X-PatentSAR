"""Closed original header cells may disprove padded raster locator boundaries.

This is geometry ownership, not text correction. Original locator coordinates,
text and scores survive; known claims and native witnesses are never waived.
"""

from .activity_header_identity import detector_header_conflict
from .cell_frame_proof import valid_cell_frame
from .source_cell_tokens import cell_lines, crosses_cell
from .source_observations import (
    project_source_observation,
    source_cell_observation,
    source_observation_status,
)


def valid_header_boundary(column):
    """Replay the sole optional closed-cell witness without trusting flags."""
    if column.get("crosses_boundary") is not False:
        return False
    if "boundary_source" not in column:
        return True
    packet = column["boundary_source"]
    bounds, dpi = column.get("bbox"), column.get("render_dpi")
    if (
        not isinstance(packet, dict)
        or packet.get("origin") != "raster"
        or source_observation_status(packet, bounds, packet.get("text")) == "invalid"
        or not crosses_cell(
            [*packet["tokens"], *packet.get("boundary_tokens", [])], bounds
        )
        or any(
            part["source"] != "raster"
            for part in [*packet["tokens"], *packet.get("boundary_tokens", [])]
        )
        or not isinstance(column.get("source_window"), dict)
        or column["source_window"].get("purpose") != "text"
        or column["source_window"].get("frame_strips") is None
        or not valid_cell_frame(column.get("source_frame"), column, bounds, dpi)
        or not isinstance(column.get("raw_text"), str)
    ):
        return False
    # A closed cell establishes where the source is, not what its text means.
    # Even a crossing locator keeps every qualified centre-owned literal claim.
    return all(
        not detector_header_conflict(line, column["raw_text"])
        for line in cell_lines(packet["tokens"], bounds)
    )


def resolve_header_boundary(column, tokens):
    """Retain a crossing as a source witness only after complete frame proof."""
    if column["crosses_boundary"] is not True:
        return column
    source = source_cell_observation(tokens, column["bbox"], native=False)
    candidate = {**column, "crosses_boundary": False, "boundary_source": source}
    return candidate if valid_header_boundary(candidate) else column


def header_boundary_matches(column, original):
    """Bind the leaf witness to the existing original header-source snapshot."""
    try:
        observed = project_source_observation(original, column["bbox"])
        crossing = crosses_cell(
            [*observed["tokens"], *observed.get("boundary_tokens", [])],
            column["bbox"],
        )
        return (
            crossing == ("boundary_source" in column)
            and (not crossing or column["boundary_source"] == observed)
            and valid_header_boundary(column)
        )
    except (KeyError, TypeError, ValueError, IndexError, OverflowError):
        return False
