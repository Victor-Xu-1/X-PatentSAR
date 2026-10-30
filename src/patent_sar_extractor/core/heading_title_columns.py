"""Original active column witnesses for full-row heading-title ownership."""

import re

from .cell_frame_proof import inside_box
from .source_geometry import overlaps


def title_column_windows(sections, number, size, original_sha, nomination, seek):
    """Use the existing column authority; no nearest box or page-half split."""
    from .heading_column_sources import COLUMN_SOURCE_ROLES, independent_columns
    from .structure_column_context import column_context_band

    if (
        type(number) is not int
        or not 1 <= number <= 20000
        or not isinstance(original_sha, str)
        or not re.fullmatch(r"[a-f0-9]{64}", original_sha)
    ):
        raise ValueError("Invalid original heading-title column identity")
    if not isinstance(sections, list) or not 1 <= len(sections) <= 25000:
        raise ValueError("Malformed original heading-title column inventory")
    if any(
        not isinstance(s, dict) or s.get("role") not in COLUMN_SOURCE_ROLES
        for s in sections
    ):
        raise ValueError("Unknown original heading-title column owner")
    diagrams = sections[0]["source"]["page_diagrams"]
    page = {
        "page_no": number,
        "page_size": size,
        "structures": [{"structure_id": d["id"], "bbox": d["bbox"]} for d in diagrams],
    }
    heading = {"nomination": {"bbox": nomination}, "original_pdf_sha256": original_sha}
    bands, seen = [], set()
    for section in sections:
        if section.get("region_id") in seen:
            raise ValueError("Duplicate original heading-title column owner")
        seen.add(section.get("region_id"))
        # Preserve the exact source association supplied by the same validator;
        # never find an owner again by matching shared diagrams or proximity.
        for column in independent_columns([section], page, heading):
            if not column["active"]:
                continue
            if not column["bbox"][1] <= seek[1] < seek[3] <= column["bbox"][3]:
                continue  # A closing edge cannot acquire a complete row owner.
            left, right = column_context_band(section["source"]["header_scope"])
            if not (nomination[2] <= left or right <= nomination[0]):
                continue
            bands.append([left, seek[1], right, seek[3]])
    return bands


def title_marks_outside_columns(marks, windows, seek):
    """Conserve full paints; partition only their portion in the observed row.

    Long original table-rule operations can extend above/below this row. Their
    full source is retained and replayed. Only an independently active foreign
    column owns the intersecting row portion. Horizontal crossing always refuses.
    """
    output = []
    for mark in marks:
        row_piece = [mark[0], max(mark[1], seek[1]), mark[2], min(mark[3], seek[3])]
        owners = [window for window in windows if inside_box(row_piece, window)]
        if len(owners) == 1:
            continue
        if owners or any(overlaps(row_piece, window) for window in windows):
            return None, "crossing_original_column_title_ink"
        output.append(mark)
    return output, None
