"""Replay original table declarations independently of successful row matches."""

import re

from .caption_role_semantics import catalog_title_role
from .printed_identifiers import identifier_key
from .source_body_context import (
    box_inside_drawing,
    original_context_extent,
    validate_page_diagrams,
)
from .source_cell_tokens import cell_lines, cell_text
from .source_evidence_identity import proof_id
from .source_section_roles import section_heading
from .source_table_captions import table_caption_nominees
from .source_table_markers import TABLE_CAPTION_START
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


def _title_window(caption, lanes, size):
    """The existing short, adjacent title-wrap limit, before any row/heading."""
    end = caption["bbox"][3]
    for lane in lanes:
        tail, count = caption["bbox"][3], 0
        for line in cell_lines(lane, [0, tail, *size]):
            top = min(t["bbox"][1] for t in line)
            bottom = max(t["bbox"][3] for t in line)
            text = cell_text(line, [0, top, size[0], bottom])
            if (
                count == 2
                or top - tail > 18
                or TABLE_CAPTION_START.match(text)
                or section_heading(text)
                or identifier_key(text, wrapped=True)
                or possible_structure_header(text)
            ):
                break
            tail, count = bottom, count + 1
        end = max(end, tail)
    return [0, caption["bbox"][1], size[0], min(size[1], end + 0.001)]


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


def _identifier_lists(chunks, page, body, lanes):
    """Keep uncertain raw lines; a footer/prose line cannot erase earlier IDs."""
    projected, lists = project_source_window(chunks, page, body), []
    for native, lane in zip((False, True), lanes, strict=True):
        texts = [cell_text(line, body) for line in cell_lines(lane, body)]
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
    for caption in table_caption_nominees(lanes[0], size, native_tokens=lanes[1]):
        if box_inside_drawing(caption["bbox"], source["page_diagrams"]):
            continue  # Drawing annotations do not introduce a page table role.
        title = _title_window(caption, lanes, size)
        if title[3] >= size[1]:
            continue
        title_chunks = project_source_window(chunks, page, title)
        packets = [p for c in title_chunks for p in c["sources"] if p["text"].strip()]
        role, _key = observed_role(packets)
        unproved_nonfinal = role == "unknown" and any(
            catalog_title_role(p["text"]) in {"nonfinal", "mixed"} for p in packets
        )
        body = [0, title[3], *size]
        body_chunks = project_source_window(chunks, page, body)
        extent = original_context_extent(
            body_chunks, body, source["page_diagrams"], column_boundaries=False
        )
        bottom = extent["body_bottom"]
        body[3] = bottom
        diagrams = [
            d
            for d in source["page_diagrams"]
            if d["bbox"][3] > body[1] and d["bbox"][1] < bottom
        ]
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
        if scope["role"] == "nonfinal" and diagram["bbox"][3] <= scope["trusted_bottom"]
    ]
