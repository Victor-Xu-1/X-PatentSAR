"""One bounded, replayable inventory from a heading to its original procedure.

All detected structures participate, including ones reserved by other source
interpreters. This does not classify a reaction's terminal product: multiple or
boundary-crossing drawings stay ambiguous. No page OCR/model is started here.
"""

import math
import re

from .heading_column_sources import (
    ambiguous_column_flow,
    foreign_column_line,
    independent_columns,
)
from .heading_page_columns import later_page_columns
from .heading_panel_scope import panel_candidate, panel_page
from .source_evidence_identity import proof_id
from .source_section_roles import (
    heading_list_hint,
    procedure_heading_boundary,
    section_heading,
)

MAX_DECLARATION_PAGES = 64
MAX_DECLARATION_STRUCTURES = 25000
_SHA = re.compile(r"[a-f0-9]{64}")


def _box(value, size):
    return bool(
        isinstance(value, list)
        and len(value) == 4
        and all(type(v) in {int, float} and math.isfinite(v) for v in value)
        and 0 <= value[0] < value[2] <= size[0]
        and 0 <= value[1] < value[3] <= size[1]
    )


def _stop(page, heading, columns=()):
    same_page = page["page_no"] == heading["page_no"]
    start = heading["nomination"]["bbox"]
    boundaries = []
    for line in page["lines"]:
        box, text = line["bbox"], line["text"]
        if not (
            procedure_heading_boundary(text)
            or section_heading(text)
            or heading_list_hint(text)
        ):
            continue
        lane = foreign_column_line(box, columns)
        if lane == "contained":
            continue
        if lane == "closing":
            boundaries.append((box[1], "foreign_column_boundary"))
            continue
        if same_page and box[1] <= start[1] + 3:
            # A simultaneous independent title has no established column lane.
            if (section_heading(text) or heading_list_hint(text)) and (
                min(box[3], start[3]) > max(box[1], start[1])
                and (box[2] < start[0] or box[0] > start[2])
            ):
                boundaries.append((start[3], "parallel_heading"))
            continue
        boundaries.append((box[1], "source_boundary"))
    return min(boundaries) if boundaries else None


def declaration_window(page, heading, columns=(), panel=None):
    if panel is None:
        return _stop(page, heading, columns), None, True
    cell, owned, complete = panel_page(page, heading, panel)
    if owned is None:
        return (heading["nomination"]["bbox"][3], "unproved_panel"), None, False
    boundary = _stop(owned, heading)
    if boundary is None:
        boundary = (cell[3], "physical_panel_boundary")
    return boundary, cell, complete


def _page_valid(page):
    if not isinstance(page, dict) or set(page) != {
        "page_no",
        "page_size",
        "lines",
        "structures",
    }:
        return False
    size = page["page_size"]
    if (
        type(page["page_no"]) is not int
        or not isinstance(size, list)
        or len(size) != 2
        or not all(
            type(v) in {int, float} and math.isfinite(v) and 0 < v <= 100000
            for v in size
        )
        or not isinstance(page["lines"], list)
        or len(page["lines"]) > 50000
        or not isinstance(page["structures"], list)
        or len(page["structures"]) > MAX_DECLARATION_STRUCTURES
    ):
        return False
    for line in page["lines"]:
        if (
            not isinstance(line, dict)
            or set(line) != {"text", "bbox", "source"}
            or not isinstance(line["text"], str)
            or len(line["text"]) > 4096
            or line["source"] not in {"native", "page_ocr"}
            or not _box(line["bbox"], size)
        ):
            return False
    return all(
        isinstance(s, dict)
        and set(s) == {"structure_id", "bbox"}
        and isinstance(s["structure_id"], str)
        and 0 < len(s["structure_id"]) <= 256
        and _box(s["bbox"], size)
        for s in page["structures"]
    )


def declaration_candidates(scope, heading):
    """Replay the complete contiguous window; return candidates and completeness.

    A partial drawing remains a candidate, never disappears to manufacture
    uniqueness. Invalid/changed packets are rejected, not treated as empty.
    """
    if (
        not isinstance(scope, dict)
        or set(scope)
        != {
            "version",
            "status",
            "original_pdf_sha256",
            "heading_source_id",
            "document_page_count",
            "pages",
            "column_sources",
            "later_columns",
            "stop",
        }
        | ({"panel"} if scope.get("version") == 4 else set())
        or type(scope["version"]) is not int
        or scope["version"] not in {3, 4}
        or scope["status"] != "observed_declaration"
        or not isinstance(scope["original_pdf_sha256"], str)
        or not _SHA.fullmatch(scope["original_pdf_sha256"])
        or scope["original_pdf_sha256"] != heading.get("original_pdf_sha256")
        or scope["heading_source_id"] != proof_id(heading)
        or type(scope["document_page_count"]) is not int
        or not 1 <= scope["document_page_count"] <= 20000
        or not isinstance(scope["pages"], list)
        or not 1 <= len(scope["pages"]) <= MAX_DECLARATION_PAGES
        or not isinstance(scope.get("later_columns"), list)
        or len(scope["later_columns"]) != len(scope["pages"]) - 1
    ):
        raise ValueError("Malformed original heading declaration scope")
    proof_id(scope)  # Keep the existing one-MiB original-region bound unchanged.
    panel = scope.get("panel")
    if scope["version"] == 4 and (panel is None or len(scope["pages"]) != 1):
        raise ValueError("Original panel must bound one complete physical page")
    if not _page_valid(scope["pages"][0]):
        raise ValueError("Malformed original heading first page")
    columns = independent_columns(scope["column_sources"], scope["pages"][0], heading)
    candidates, identities, expected_stop, ambiguous_flow = [], set(), None, False
    for offset, page in enumerate(scope["pages"]):
        number = heading["page_no"] + offset
        if (
            not _page_valid(page)
            or page["page_no"] != number
            or number > scope["document_page_count"]
            or expected_stop is not None
        ):
            raise ValueError("Original heading declaration page inventory differs")
        if offset == 0 and page["page_size"] != heading["page_size"]:
            raise ValueError("Original heading declaration geometry differs")
        current_columns = columns
        if offset:
            witness = scope["later_columns"][offset - 1]
            if (
                not isinstance(witness, dict)
                or set(witness) != {"page_no", "sources"}
                or type(witness["page_no"]) is not int
                or witness["page_no"] != number
            ):
                raise ValueError("Original later-column page identity differs")
            current_columns = later_page_columns(witness["sources"], page, heading)
        excluded = {d["id"] for column in current_columns for d in column["diagrams"]}
        boundary, cell, panel_complete = declaration_window(
            page, heading, current_columns, panel
        )
        ambiguous_flow |= not panel_complete
        lower = heading["nomination"]["bbox"][3] if offset == 0 else 0
        upper = boundary[0] if boundary else page["page_size"][1]
        for structure in page["structures"]:
            sid, box = structure["structure_id"], structure["bbox"]
            if sid in identities:
                raise ValueError("Duplicate original heading structure identity")
            identities.add(sid)
            if len(identities) > MAX_DECLARATION_STRUCTURES:
                raise ValueError(
                    "Original heading structure inventory exceeds its bound"
                )
            included, inside = (
                panel_candidate(box, lower, upper, cell)
                if cell is not None
                else (
                    box[3] > lower and box[1] < upper,
                    lower <= box[1] < box[3] <= upper,
                )
            )
            if included and sid not in excluded:
                ambiguous_flow |= offset == 0 and ambiguous_column_flow(
                    box, heading, columns
                )
                candidates.append(
                    {
                        **structure,
                        "page_no": number,
                        "inside": inside,
                    }
                )
        if boundary:
            expected_stop = {"kind": boundary[1], "page_no": number, "y": upper}
        elif number == scope["document_page_count"]:
            expected_stop = {"kind": "document_end", "page_no": number, "y": upper}
    if expected_stop is None and len(scope["pages"]) == MAX_DECLARATION_PAGES:
        page = scope["pages"][-1]
        expected_stop = {
            "kind": "page_limit",
            "page_no": page["page_no"],
            "y": page["page_size"][1],
        }
    if expected_stop is None or scope["stop"] != expected_stop:
        raise ValueError("Original heading declaration was shortened or changed")
    # Exact types matter for persisted boundary coordinates too.
    stop = scope["stop"]
    if (
        not isinstance(stop, dict)
        or type(stop.get("page_no")) is not int
        or type(stop.get("y")) not in {int, float}
    ):
        raise ValueError("Malformed original heading declaration stop")
    return candidates, not ambiguous_flow and stop["kind"] not in {
        "page_limit",
        "parallel_heading",
        "foreign_column_boundary",
        "unproved_panel",
    }
