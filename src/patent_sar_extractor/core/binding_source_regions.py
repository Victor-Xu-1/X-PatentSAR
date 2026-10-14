"""Characterization references reuse the existing complete original grid proof."""

import re
from itertools import pairwise

from .activity_grid_context import _prefix
from .activity_grid_role_observation import observe_characterization
from .activity_grid_role_proof import valid_role_scope
from .activity_header_evidence import proof_id
from .printed_identifiers import (
    LABEL_KIND,
    PRINTED_ID,
    identifier_key,
    identifier_width,
)
from .source_geometry import _box
from .source_section_roles import nonfinal_original_label, section_heading
from .table_geometry import detect_ruled_table_regions, page_tokens

_WRAPPER_GAP = re.compile(
    rf"({LABEL_KIND})\s*(?={PRINTED_ID}(?![\w/-]))", re.IGNORECASE
)


def _reference_text(text):
    # Only the existing lexical wrapper gap is equivalent. Never join digits,
    # suffixes or hyphenated components; originals remain unchanged in proof.
    return _WRAPPER_GAP.sub(r"\1 ", " ".join(identifier_width(text).split())).casefold()


def reference_regions(page, *, original_pdf_sha256, grids=None, tokens=None):
    grids = detect_ruled_table_regions(page, dpi=240) if grids is None else grids
    if not grids:
        return []
    tokens = (
        page_tokens(page, dpi=200, allow_tesseract=False) if tokens is None else tokens
    )
    regions = []
    for grid in grids:
        scope = observe_characterization(page, grid, tokens, _prefix(tokens, grid))
        if scope is None:
            continue
        record = {
            "page_no": page.number + 1,
            "bbox": [scope["xs"][0], scope["ys"][0], scope["xs"][-1], scope["ys"][-1]],
            "role_scope": scope,
            "status": "observed_characterization",
            "original_pdf_sha256": original_pdf_sha256,
            "geometry_space": "rendered",
        }
        if not valid_role_scope(record):
            raise ValueError("Unproved original characterization region")
        regions.append({**record, "region_id": proof_id(record)})
    return regions


def collect_reference_regions(
    doc, pages, sections, *, original_pdf_sha256, grids_for_page, tokens_for_page
):
    """One inventory reuses call-local grid/token ownership, not a repair chain."""
    output = {}
    for index in pages:
        page = doc[index]
        grids = grids_for_page(page)
        regions = reference_regions(
            page,
            original_pdf_sha256=original_pdf_sha256,
            grids=grids,
            tokens=tokens_for_page(page) if grids else [],
        )
        output[index] = regions
        sections.extend(
            {
                "role": "characterization_region",
                "page_no": index + 1,
                "source_region": region,
            }
            for region in regions
        )
        sections.extend(
            reference
            for region in regions
            for reference in identifier_references(region)
        )
    return output


def reference_cell(line, regions):
    """Only a wholly owned original line, never a whole-page vertical hint."""
    if line.get("geometry_space") != "rendered" or line.get("source") not in {
        "native",
        "page_ocr",
    }:
        return None
    box = _box(line["bbox"])
    owners = []
    for region in regions:
        scope = region["role_scope"]
        for row, (y0, y1) in enumerate(pairwise(scope["ys"])):
            if row < scope["roles"]["data_start"]:
                continue
            for column, (x0, x1) in enumerate(pairwise(scope["xs"])):
                role = scope["roles"]["columns"][column]
                if role not in {"identifier", "preparation"}:
                    continue
                if x0 <= box.x0 < box.x1 <= x1 and y0 <= box.y0 < box.y1 <= y1:
                    text = _reference_text(line.get("text", ""))
                    originals = [
                        observation["matrix"][row][column]
                        for observation in scope["observations"]
                    ]
                    if not text or not all(
                        re.search(re.escape(text) + r"(?![\w/-])", _reference_text(raw))
                        for raw in originals
                    ):
                        continue
                    owners.append(
                        {
                            "source_region": region["region_id"],
                            "grid_row": row,
                            "grid_column": column,
                            "reference_kind": role,
                        }
                    )
    return owners[0] if len(owners) == 1 else None


def identifier_references(region):
    """Inventory every primary physical cell, independently of title nomination."""
    scope = region["role_scope"]
    column = scope["roles"]["columns"].index("identifier")
    references = []
    for row in range(scope["roles"]["data_start"], len(scope["ys"]) - 1):
        originals = [
            observation["matrix"][row][column] for observation in scope["observations"]
        ]
        keys, nonfinal = set(), set()
        for raw in originals:
            heading = section_heading(raw)
            keys.add(
                heading["identifier"]
                if heading
                else identifier_key(raw, wrapped=True, terminal_period=True)
            )
            nonfinal.add(nonfinal_original_label(raw))
        hint = scope["native_hints"][row][column]
        if hint.strip():
            heading = section_heading(hint)
            keys.add(
                heading["identifier"]
                if heading
                else identifier_key(hint, wrapped=True, terminal_period=True)
            )
            nonfinal.add(nonfinal_original_label(hint))
        header = (
            scope["observations"][0]["matrix"][0][column]
            if scope["roles"]["data_start"]
            else ""
        )
        intermediate_header = nonfinal_original_label(header)
        explicit_final = any(
            section_heading(raw) and not nonfinal_original_label(raw)
            for raw in originals
        )
        role = (
            "intermediate"
            if intermediate_header or nonfinal == {True}
            else "terminal_reference"
        )
        if (
            len(keys) != 1
            or "" in keys
            or len(nonfinal) != 1
            or intermediate_header
            and explicit_final
        ):
            role = "ambiguous"
        references.append(
            {
                "role": "characterization_identifier",
                "page_no": region["page_no"],
                "source_region": region["region_id"],
                "grid_row": row,
                "grid_column": column,
                "identifier": next(iter(keys)) if len(keys) == 1 else "",
                "source_role": role,
                "raw_texts": originals,
                "bbox": [
                    scope["xs"][column],
                    scope["ys"][row],
                    scope["xs"][column + 1],
                    scope["ys"][row + 1],
                ],
            }
        )
    return references
