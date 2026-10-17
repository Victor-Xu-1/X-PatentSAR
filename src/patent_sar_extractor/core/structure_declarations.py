"""Capture declarations in the existing binder ledger and shared source reader."""

from collections import defaultdict

from .activity_header_evidence import proof_id
from .caption_role_semantics import catalog_title_role, has_continuation_caption
from .source_document import document_sha256
from .source_geometry import SourceTokens
from .source_table_captions import table_caption_nominees
from .source_window_chunks import observe_source_window
from .structure_declaration_scopes import (
    PAGE_ROLE,
    PAGE_STATUS,
    declaration_scopes,
    nonfinal_declaration_diagrams,
)
from .structure_table_headers import possible_structure_header


def declaration_page_hint(text):
    return (
        possible_structure_header(text)
        or has_continuation_caption(text)
        or any(
            catalog_title_role(line) in {"compound", "nonfinal", "mixed"}
            for line in str(text).splitlines()
        )
    )


def observe_declaration_pages(doc, structures, pages, page_texts, tokens_for_page):
    by_page, sections, withheld = defaultdict(list), [], set()
    for structure in structures:
        by_page[structure["page_no"] - 1].append(structure)
    original_sha = None
    for index in sorted(set(pages)):
        if type(index) is not int or not 0 <= index < len(doc):
            continue
        page = doc[index]
        if not callable(getattr(page, "get_image_info", None)) or (
            not by_page[index] and not declaration_page_hint(page_texts.get(index, ""))
        ):
            continue
        tokens = tokens_for_page(page)
        size = [page.rect.width, page.rect.height]
        if not isinstance(tokens, SourceTokens) or not table_caption_nominees(
            tokens, size
        ):
            continue
        if original_sha is None:
            original_sha = document_sha256(doc)
        source = {
            "status": PAGE_STATUS,
            "version": 1,
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
        }
        scopes = declaration_scopes(source)
        if not scopes:
            continue
        sections.append(
            {
                "role": PAGE_ROLE,
                "status": PAGE_STATUS,
                "page_no": index + 1,
                "region_id": proof_id(source),
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
