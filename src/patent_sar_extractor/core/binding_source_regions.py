"""Characterization references reuse the existing complete original grid proof."""

import re
from itertools import pairwise

from .activity_context_geometry import context_region, grid_box
from .activity_grid_context import _prefix
from .activity_grid_role_observation import observe_characterization
from .binding_progress import observed_items
from .printed_identifiers import (
    LABEL_KIND,
    PRINTED_ID,
    identifier_key,
    identifier_width,
)
from .reference_region_identity import reference_region_id
from .source_fragment_context import observe_fragment_context
from .source_geometry import _box
from .source_grid_edges import original_grid_edges
from .source_role_fragments import fragment_texts, observe_fragments
from .source_role_observations import scope_observations
from .source_section_roles import nonfinal_original_label, section_heading
from .table_geometry import detect_ruled_table_regions, page_tokens

_WRAPPER_GAP = re.compile(
    rf"({LABEL_KIND})\s*(?={PRINTED_ID}(?![\w/-]))", re.IGNORECASE
)


def _reference_text(text):
    # Only the existing lexical wrapper gap is equivalent. Never join digits,
    # suffixes or hyphenated components; originals remain unchanged in proof.
    return _WRAPPER_GAP.sub(r"\1 ", " ".join(identifier_width(text).split())).casefold()


def reference_regions(
    page, *, original_pdf_sha256, grids=None, tokens=None, evidence_sink=None
):
    grids = detect_ruled_table_regions(page, dpi=240) if grids is None else grids
    if not grids:
        return []
    tokens = (
        page_tokens(page, dpi=200, allow_tesseract=False) if tokens is None else tokens
    )
    regions = []
    boxes = [grid_box(grid) for grid in grids]
    for original_grid in grids:
        grid = context_region(original_grid, boxes)
        rejected = []
        scope = observe_characterization(
            page, grid, tokens, _prefix(tokens, grid), evidence_sink=rejected
        )
        if evidence_sink is not None:
            evidence_sink.extend(
                scope_observations(
                    rejected, page.number + 1, original_pdf_sha256=original_pdf_sha256
                )
            )
        if scope is None:
            continue
        record = {
            "page_no": page.number + 1,
            "bbox": [scope["xs"][0], scope["ys"][0], scope["xs"][-1], scope["ys"][-1]],
            "role_scope": scope,
            "status": "observed_characterization",
            "original_pdf_sha256": original_pdf_sha256,
            "geometry_space": "rendered",
            "grid_edges": original_grid_edges(page, original_grid),
        }
        record["row_fragments"] = observe_fragments(page, record["grid_edges"], tokens)
        record["fragment_context"] = observe_fragment_context(
            tokens, record["grid_edges"], record["row_fragments"]
        )
        regions.append({**record, "region_id": reference_region_id(record)})
    return regions


def collect_reference_regions(
    doc,
    pages,
    sections,
    *,
    original_pdf_sha256,
    grids_for_page,
    tokens_for_page,
    role_observations=None,
    progress=None,
):
    """One inventory reuses call-local grid/token ownership, not a repair chain."""
    output = {}
    for index in observed_items("reference_sources", pages, progress):
        page = doc[index]
        grids = grids_for_page(page)
        regions = reference_regions(
            page,
            original_pdf_sha256=original_pdf_sha256,
            grids=grids,
            tokens=tokens_for_page(page) if grids else [],
            evidence_sink=role_observations,
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


def _reference_cells(region):
    scope = region["role_scope"]
    for row, (y0, y1) in enumerate(pairwise(scope["ys"])):
        if row < scope["roles"]["data_start"]:
            continue
        for column, (x0, x1) in enumerate(pairwise(scope["xs"])):
            yield {
                "grid_row": row,
                "grid_column": column,
                "bbox": [x0, y0, x1, y1],
                "qualified": True,
                "raw_texts": [o["matrix"][row][column] for o in scope["observations"]],
                "hint": scope["native_hints"][row][column],
            }
    for index, fragment in enumerate(region.get("row_fragments", [])):
        source = fragment["source_cells"]
        if source is None:
            continue
        row = -1 if fragment["edge"] == "top" else len(scope["ys"]) - 1
        for column, (x0, x1) in enumerate(pairwise(scope["xs"])):
            qualified = fragment_texts(region, fragment, column)
            yield {
                "grid_row": row,
                "grid_column": column,
                "fragment_index": index,
                "bbox": [x0, fragment["bbox"][1], x1, fragment["bbox"][3]],
                "qualified": qualified is not None,
                "raw_texts": [o["matrix"][0][column] for o in source["observations"]],
                "hint": source["native_hints"][0][column],
            }


def reference_cell(
    line, regions, *, permitted_roles=frozenset({"identifier", "preparation"})
):
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
        for cell in _reference_cells(region):
            role = scope["roles"]["columns"][cell["grid_column"]]
            if role not in permitted_roles or not cell["qualified"]:
                continue
            x0, y0, x1, y1 = cell["bbox"]
            if x0 <= box.x0 < box.x1 <= x1 and y0 <= box.y0 < box.y1 <= y1:
                text = _reference_text(line.get("text", ""))
                if not text or not all(
                    re.search(re.escape(text) + r"(?![\w/-])", _reference_text(raw))
                    for raw in cell["raw_texts"]
                ):
                    continue
                owners.append(
                    {
                        "source_region": region["region_id"],
                        "reference_kind": role,
                        **{
                            k: cell[k]
                            for k in ("grid_row", "grid_column", "fragment_index")
                            if k in cell
                        },
                    }
                )
    return owners[0] if len(owners) == 1 else None


def identifier_references(region):
    """Inventory every primary physical cell, independently of title nomination."""
    scope = region["role_scope"]
    column = scope["roles"]["columns"].index("identifier")
    references = []
    for cell in _reference_cells(region):
        if cell["grid_column"] != column:
            continue
        originals = cell["raw_texts"]
        if (
            "fragment_index" in cell
            and cell["qualified"]
            and not any(text.strip() for text in [*originals, cell["hint"]])
        ):
            continue  # Retained blank fragment, never a fabricated compound or zero.
        keys, nonfinal = set(), set()
        for raw in originals:
            heading = section_heading(raw)
            keys.add(
                heading["identifier"]
                if heading
                else identifier_key(raw, wrapped=True, terminal_period=True)
            )
            nonfinal.add(nonfinal_original_label(raw))
        hint = cell["hint"]
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
            not cell["qualified"]
            or len(keys) != 1
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
                **{
                    k: cell[k]
                    for k in ("grid_row", "grid_column", "fragment_index")
                    if k in cell
                },
                "identifier": next(iter(keys)) if len(keys) == 1 else "",
                "source_role": role,
                "raw_texts": originals,
                "bbox": cell["bbox"],
            }
        )
    return references
