"""Replay original table declarations independently of successful row matches."""

import re

from .activity_context_geometry import context_band
from .caption_role_semantics import catalog_title_role
from .logical_column_partitions import caption_logical_band, nominate_unruled_headers
from .printed_identifiers import identifier_key
from .ruled_continuation_context import validate_page_grid
from .source_body_context import (
    box_inside_drawing,
    intersecting_source_diagrams,
    original_context_extent,
    validate_page_diagrams,
)
from .source_cell_tokens import cell_lines, cell_text
from .source_evidence_identity import proof_id
from .source_section_roles import section_heading
from .source_table_captions import caption_context_geometry, table_caption_nominees
from .source_table_markers import table_body_boundary
from .source_table_roles import observed_role
from .source_window_chunks import (
    project_source_window,
    validate_source_window,
    window_source_tokens,
)
from .structure_table_headers import possible_structure_header

PAGE_ROLE = "structure_declaration_page"
PAGE_STATUS = "observed_original_structure_declarations"
REFERENCE_ROLE = "structure_declaration_reference"


def _title_window(caption, lanes, size, band):
    """The existing short, adjacent title-wrap limit, before any row/heading."""
    end = caption["bbox"][3]
    for lane in lanes:
        tail, count = caption["bbox"][3], 0
        for line in cell_lines(lane, [band[0], tail, band[1], size[1]]):
            top = min(t["bbox"][1] for t in line)
            bottom = max(t["bbox"][3] for t in line)
            text = cell_text(line, [band[0], top, band[1], bottom])
            if (
                count == 2
                or top - tail > 18
                or table_body_boundary(text)
                or section_heading(text)
                or identifier_key(text, wrapped=True)
                or possible_structure_header(text)
            ):
                break
            tail, count = bottom, count + 1
        end = max(end, tail)
    return [band[0], caption["bbox"][1], band[1], min(size[1], end + 0.001)]


def validate_declaration_page(source):
    if (
        not isinstance(source, dict)
        or set(source)
        != {
            "status",
            "version",
            "original_pdf_sha256",
            "page_no",
            "page_size",
            "page_context",
            "page_diagrams",
            "page_grids",
        }
        or source["status"] != PAGE_STATUS
        or type(source["version"]) is not int
        or source["version"] != 1
        or not isinstance(source["original_pdf_sha256"], str)
        or not re.fullmatch(r"[a-f0-9]{64}", source["original_pdf_sha256"])
        or type(source["page_no"]) is not int
        or not 1 <= source["page_no"] <= 20000
        or not isinstance(source["page_size"], list)
        or len(source["page_size"]) != 2
    ):
        raise ValueError("Malformed original table-declaration page")
    validate_source_window(source["page_context"], [0, 0, *source["page_size"]])
    validate_page_diagrams(source["page_diagrams"], source["page_size"])
    if not isinstance(source["page_grids"], list) or len(source["page_grids"]) > 4096:
        raise ValueError("Malformed original declaration grid inventory")
    for grid in source["page_grids"]:
        validate_page_grid(grid, source["page_size"])


def _identifier_lists(chunks, page, body, lanes):
    """Keep uncertain raw lines; a footer/prose line cannot erase earlier IDs."""
    projected, lists = project_source_window(chunks, page, body), []
    for native, lane in zip((False, True), lanes, strict=True):
        lines = cell_lines(lane, body)
        texts = [cell_text(line, body) for line in lines]
        keys = [identifier_key(text, wrapped=True) for text in texts]
        packets = [
            next(p for p in chunk["sources"] if p["origin"] == "native")
            if native
            else chunk["sources"][0]
            for chunk in projected
        ]
        if keys:
            lists.append(
                {
                    "identifiers": keys,
                    "lines": [
                        {
                            "text": text,
                            "bbox": [
                                min(p["bbox"][0] for p in line),
                                min(p["bbox"][1] for p in line),
                                max(p["bbox"][2] for p in line),
                                max(p["bbox"][3] for p in line),
                            ],
                            "source": "native"
                            if all(p["source"] == "native" for p in line)
                            else "page_ocr",
                            "geometry_space": "rendered",
                        }
                        for text, line in zip(texts, lines, strict=True)
                    ],
                    "qualified": all(
                        p["status"] == "qualified" for p in packets if p["text"].strip()
                    ),
                }
            )
    return lists if any(any(item["identifiers"]) for item in lists) else []


def declaration_scopes(source):
    """No artificial columns/rows: titles, complete contexts and actual diagrams."""
    validate_declaration_page(source)
    size, chunks = source["page_size"], source["page_context"]
    page = [0, 0, *size]
    lanes = [
        window_source_tokens(chunks, page, native=native) for native in (False, True)
    ]
    page_source_id = proof_id(source)
    output = []
    captions = table_caption_nominees(lanes[0], size, native_tokens=lanes[1])
    logical_headers = nominate_unruled_headers(lanes[0], size, native_tokens=lanes[1])
    for caption in captions:
        if box_inside_drawing(caption["bbox"], source["page_diagrams"]):
            continue  # Drawing annotations do not introduce a page table role.
        geometry = caption_context_geometry(caption, captions, source["page_grids"])
        left, right = (
            context_band(geometry)
            if geometry is not None
            else caption_logical_band(caption, captions, logical_headers, size)
            or [0, size[0]]
        )
        band = [max(0, left), min(size[0], right)]
        title = _title_window(caption, lanes, size, band)
        if title[3] >= size[1]:
            continue
        title_chunks = project_source_window(chunks, page, title)
        packets = [p for c in title_chunks for p in c["sources"] if p["text"].strip()]
        role, _key = observed_role(packets)
        unproved_nonfinal = role == "unknown" and any(
            catalog_title_role(p["text"]) in {"nonfinal", "mixed"} for p in packets
        )
        body = [band[0], title[3], band[1], size[1]]
        body_chunks = project_source_window(chunks, page, body)
        extent = original_context_extent(
            body_chunks,
            body,
            intersecting_source_diagrams(source["page_diagrams"], body),
            column_boundaries=False,
        )
        bottom = extent["body_bottom"]
        body[3] = bottom
        diagrams = (
            intersecting_source_diagrams(source["page_diagrams"], body)
            if body[1] < bottom
            else []
        )
        # These are raw reference candidates, not final structures or measured
        # values. Metadata/measurement/footer attribution remains explicit work.
        lists = (
            _identifier_lists(chunks, page, body, lanes)
            if role == "compound" and not diagrams and bottom > body[1]
            else []
        )
        if (
            not diagrams
            and role not in {"nonfinal", "conflict"}
            and not lists
            and not unproved_nonfinal
        ):
            continue
        identity = proof_id(
            {
                "status": "observed_original_table_declaration",
                "page_source": page_source_id,
                "caption": caption,
            }
        )
        output.append(
            {
                "source_region": identity,
                "page_no": source["page_no"],
                "bbox": body,
                "role": role,
                "caption": caption,
                "diagrams": diagrams,
                "identifier_lists": lists,
                "trusted_bottom": extent["trusted_bottom"],
                "unproved_boundaries": extent["unproved_boundaries"],
                "unproved_nonfinal_role": unproved_nonfinal,
            }
        )
    return output


def nonfinal_declaration_diagrams(scope):
    """Only the positively proved prefix can exclude original diagrams."""
    return [
        diagram
        for diagram in scope["diagrams"]
        if scope["role"] == "nonfinal"
        and diagram["bbox"][3] <= scope["trusted_bottom"]
        and scope["bbox"][0]
        <= diagram["bbox"][0]
        < diagram["bbox"][2]
        <= scope["bbox"][2]
    ]
