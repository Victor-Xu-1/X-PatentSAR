"""Reuse a numbered physical header's original title in the same source ledger."""

from .activity_context_geometry import grid_box
from .caption_role_proof import caption_role_status
from .caption_role_titles import project_caption_titles
from .source_evidence_identity import proof_id
from .structure_column_anchors import ANCHOR_ROLE, column_anchor_roles
from .structure_header_context import original_header_context_role


def header_catalogue_scope(section, original_pdf_sha256):
    """A pure schema adapter: no reader, role inference or new source owner.

    Continued headers belong to their existing continuation proof. Only an
    original physical header on this same page can supply a catalogue context.
    Header words alone cannot override an unknown/contradictory original title.
    """
    if not isinstance(section, dict) or section.get("role") != ANCHOR_ROLE:
        raise ValueError("Malformed original numbered-header owner")
    source = section.get("source")
    header = source.get("header_scope") if isinstance(source, dict) else None
    if not isinstance(header, dict):
        raise TypeError("Missing original numbered-header source")
    if header.get("kind") != "original_ruled_columns":
        return None
    if (
        set(section) != {"role", "status", "page_no", "region_id", "source"}
        or section["status"] != source.get("status")
        or section["region_id"] != proof_id(source)
        or type(section["page_no"]) is not int
        or section["page_no"] != header.get("page_no")
        or header.get("original_pdf_sha256") != original_pdf_sha256
    ):
        raise ValueError("Foreign or changed original numbered-header identity")
    column_anchor_roles(source)  # Validate its complete header/body, not a saved role.
    contexts = header["context_sources"]
    if not contexts:
        return None  # A top-of-page header cannot invent a preceding title.
    geometry, axes = header["context_geometry"], header["grid_axes"]
    role, key = original_header_context_role(
        contexts,
        axes["ys"][0],
        header["page_size"][0],
        geometry=geometry,
        grid_axes=axes,
        parallel_grids=header.get("parallel_grids"),
        page_grids=header.get("page_grids"),
    )
    scope = {
        "version": 1,
        "page_no": header["page_no"],
        "table_bbox": grid_box(axes),
        "grid_axes": axes,
        "context_geometry": geometry,
        "window": contexts[0]["bbox"],
        "observations": project_caption_titles(contexts, geometry),
        "role": role,
        "table_key": key,
        "sources": contexts,
        **(
            {"parallel_grids": header["parallel_grids"]}
            if "parallel_grids" in header
            else {}
        ),
        **({"page_grids": header["page_grids"]} if "page_grids" in header else {}),
    }
    if caption_role_status(scope, section["page_no"], scope["table_bbox"]) != role:
        raise ValueError("Original numbered-header title cannot be replayed")
    return scope
