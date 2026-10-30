"""Capture declarations in the existing binder ledger and shared source reader."""

from collections import defaultdict

from .activity_context_geometry import grid_axes
from .binding_progress import observed_items
from .caption_role_semantics import catalog_title_role, has_continuation_caption
from .source_document import document_sha256
from .source_geometry import SourceTokens
from .source_table_captions import table_caption_nominees
from .source_window_chunks import observe_source_window
from .structure_declaration_catalogues import catalogue_scopes_for_grids
from .structure_declaration_columns import original_logical_columns
from .structure_declaration_continuations import physical_declaration_columns
from .structure_declaration_scopes import (
    PAGE_ROLE,
    PAGE_STATUS,
    declaration_scopes_with_identity,
    declaration_title_nominations,
    nonfinal_declaration_diagrams,
)
from .structure_table_headers import possible_structure_header
from .title_geometry_memo import title_geometry_call


def declaration_page_hint(text):
    return (
        possible_structure_header(text)
        or has_continuation_caption(text)
        or any(
            catalog_title_role(line) in {"compound", "nonfinal", "mixed", "conflict"}
            for line in str(text).splitlines()
        )
    )


@title_geometry_call
def observe_declaration_pages(
    doc,
    structures,
    pages,
    page_texts,
    tokens_for_page,
    *,
    grids_for_page=None,
    caption_roles=None,
    column_sections=(),
    progress=None,
):
    if grids_for_page is None:
        from .table_geometry import detect_ruled_table_regions

        grids_for_page = detect_ruled_table_regions
    by_page, columns_by_page, sections, withheld = (
        defaultdict(list),
        defaultdict(list),
        [],
        set(),
    )
    for section in column_sections:
        if not isinstance(section, dict):
            raise TypeError("Malformed original numbered-column inventory")
        if section.get("role") not in {
            "structure_column_anchor",
            "unruled_structure_region",
        }:
            continue
        number = section.get("page_no")
        if type(number) is not int or not 1 <= number <= len(doc):
            raise ValueError("Original numbered-column page leaves its document")
        columns_by_page[number].append(section)
    for structure in structures:
        by_page[structure["page_no"] - 1].append(structure)
    original_sha = None
    for index in observed_items("declaration_sources", sorted(set(pages)), progress):
        if type(index) is not int or not 0 <= index < len(doc):
            continue
        page = doc[index]
        if not callable(getattr(page, "get_image_info", None)):
            continue
        grids = [grid_axes(grid) for grid in grids_for_page(page)]
        if (
            not by_page[index]
            and not grids
            and not declaration_page_hint(page_texts.get(index, ""))
        ):
            continue
        tokens = tokens_for_page(page)
        size = [page.rect.width, page.rect.height]
        if not isinstance(tokens, SourceTokens) or (
            not grids and not table_caption_nominees(tokens, size)
        ):
            continue
        if original_sha is None:
            original_sha = document_sha256(doc)
        logical_columns = original_logical_columns(columns_by_page[index + 1])
        continued_columns = physical_declaration_columns(columns_by_page[index + 1])
        source = {
            "status": PAGE_STATUS,
            "version": 4 if continued_columns else 3 if logical_columns else 2,
            "original_pdf_sha256": original_sha,
            "page_no": index + 1,
            "page_size": size,
            "page_context": observe_source_window(tokens, [0, 0, *size]),
            "page_diagrams": sorted(
                [
                    {
                        "id": str(s["id"]),
                        "bbox": [s[k] for k in ("x0", "y0", "x1", "y1")],
                    }
                    for s in by_page[index]
                ],
                key=lambda d: (d["bbox"][1], d["bbox"][0], d["id"]),
            ),
            "page_grids": grids,
            "catalogue_scopes": catalogue_scopes_for_grids(
                index + 1,
                grids,
                caption_roles,
                column_sections=columns_by_page[index + 1],
                original_pdf_sha256=original_sha,
            ),
            **(
                {"logical_columns": logical_columns}
                if logical_columns or continued_columns
                else {}
            ),
            **({"continued_columns": continued_columns} if continued_columns else {}),
        }
        from .title_source_capture import attach_title_sources

        nominations = declaration_title_nominations(source)
        parents = [p for chunk in source["page_context"] for p in chunk["sources"]]
        observed = iter(attach_title_sources(page, parents, nominations))
        for chunk in source["page_context"]:
            chunk["sources"] = [next(observed) for _ in chunk["sources"]]
        source_id, scopes = declaration_scopes_with_identity(source)
        if not scopes and not grids:
            continue
        sections.append(
            {
                "role": PAGE_ROLE,
                "status": PAGE_STATUS,
                "page_no": index + 1,
                "region_id": source_id,
                "source": source,
            }
        )
        withheld.update(
            d["id"]
            for scope in scopes
            for d in (
                scope["diagrams"]
                if scope["role"] == "conflict"
                else nonfinal_declaration_diagrams(scope)
            )
        )
    return sections, withheld
