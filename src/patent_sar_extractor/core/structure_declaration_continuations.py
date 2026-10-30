"""Existing headerless physical-column proof joins the declaration ledger."""

from .source_window_chunks import validate_source_overlap
from .title_context_source import TITLE_CONTEXT
from .title_ink_geometry import title_ink_rows
from .unruled_body_scope import body_context_window


def physical_declaration_columns(sections):
    return [
        section
        for section in sections
        if section.get("role") == "structure_column_anchor"
        and section["source"]["header_scope"].get("kind") == "continued_ruled_columns"
    ]


def validate_continued_columns(page):
    from .heading_column_sources import checked_column_source

    columns = page.get("continued_columns", [])
    if not isinstance(columns, list) or len(columns) > 4096:
        raise ValueError("Malformed original declaration continued-column inventory")
    expected = {d["id"]: d["bbox"] for d in page["page_diagrams"]}
    original = {"page_no": page["page_no"], "page_size": page["page_size"]}
    seen = set()
    for section in columns:
        checked_column_source(section, original, page["original_pdf_sha256"], expected)
        source = section["source"]
        header = source["header_scope"]
        if (
            section["role"] != "structure_column_anchor"
            or header.get("kind") != "continued_ruled_columns"
            or header["page_grids"] != page["page_grids"]
            or page["page_grids"].count(source["grid_axes"]) != 1
            or section["region_id"] in seen
        ):
            raise ValueError("Foreign or changed original declaration continuation")
        seen.add(section["region_id"])
        for chunks, window in (
            (source["body_context"], body_context_window(header)),
            (
                header["leading_context"],
                [0, 0, page["page_size"][0], header["grid_axes"]["ys"][1]],
            ),
        ):
            validate_source_overlap(
                page["page_context"], [0, 0, *page["page_size"]], chunks, window
            )
    return columns


def continued_catalogue_role(page, catalogue):
    """No new title is required only by an already-proved continuation.

    Preserve the unresolved/unknown raw caption observation. This is a join to
    its complete registered column ancestry, not a blankness certificate or a
    later OCR vote. Any retained current title ink/word/weak attempt still vetoes.
    """
    from .structure_column_anchors import column_anchor_roles

    if catalogue["role"] not in {"unknown", "unresolved"} or any(
        p["text"].strip() for p in catalogue["observations"]
    ):
        return None
    for parent in catalogue["sources"]:
        ink = parent[TITLE_CONTEXT]["ink_source"]
        if parent["text"].strip() or ink is None or title_ink_rows(ink) != ([], None):
            return None
    owners = [
        s
        for s in page.get("continued_columns", [])
        if s["source"]["grid_axes"] == catalogue["grid_axes"]
    ]
    if len(owners) != 1:
        return None
    roles = column_anchor_roles(owners[0]["source"])
    return (roles["role"], owners[0]["region_id"]) if roles is not None else None
