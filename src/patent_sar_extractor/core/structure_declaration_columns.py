"""Share original logical-column titles with the existing declaration ledger."""

from .caption_role_semantics import catalog_title_role
from .cell_frame_proof import inside_box
from .source_body_context import intersecting_source_diagrams
from .source_evidence_identity import proof_id
from .source_geometry import overlaps
from .source_observations import project_source_observation
from .source_table_roles import observed_role, title_texts
from .source_window_chunks import source_packet_projection, validate_source_overlap
from .structure_column_scopes import original_column_context, original_column_title_args
from .unruled_body_scope import (
    body_context_window,
    column_body_extent,
    column_context_window,
)
from .unruled_structure_layout import region_plan


def original_logical_columns(sections):
    """Retain actual header owners, not continuations or invented printed grids."""
    return [
        section
        for section in sections
        if section.get("role") == "unruled_structure_region"
        and section["source"]["header_scope"].get("kind") is None
        and section["source"]["header_scope"]["context_sources"]
    ]


def validate_logical_columns(page):
    columns = page.get("logical_columns", [])
    if not isinstance(columns, list) or len(columns) > 4096:
        raise ValueError("Malformed original declaration logical-column inventory")
    seen = set()
    for section in columns:
        if (
            not isinstance(section, dict)
            or set(section) != {"role", "status", "page_no", "region_id", "source"}
            or section["role"] != "unruled_structure_region"
            or not isinstance(section["source"], dict)
        ):
            raise ValueError("Malformed original declaration logical-column owner")
        source = section["source"]
        region_plan(source)  # The existing complete header/body authority only.
        header = source["header_scope"]
        if (
            header.get("kind") is not None
            or not header["context_sources"]
            or section["status"] != source["status"]
            or type(section["page_no"]) is not int
            or section["page_no"] != page["page_no"]
            or header["page_no"] != page["page_no"]
            or header["page_size"] != page["page_size"]
            or header["original_pdf_sha256"] != page["original_pdf_sha256"]
            or header["page_grids"] != page["page_grids"]
            or source["page_diagrams"] != page["page_diagrams"]
            or section["region_id"] != proof_id(source)
            or section["region_id"] in seen
        ):
            raise ValueError("Foreign or changed original declaration logical column")
        seen.add(section["region_id"])
        validate_source_overlap(
            page["page_context"],
            [0, 0, *page["page_size"]],
            source["body_context"],
            body_context_window(header),
        )
        if any(
            not source_packet_projection(packet, page["page_context"], packet["bbox"])
            for packet in [*header["context_sources"], *header["source_observations"]]
        ):
            raise ValueError("Original logical title differs from its full page source")
    return columns


def logical_column_owns_caption(page, caption):
    """Reuse only a literal nomination retained by this same original header."""
    return any(
        overlaps(caption["bbox"], packet["bbox"])
        and inside_box(caption["bbox"], packet["bbox"])
        and caption["text"]
        == project_source_observation(packet, caption["bbox"])["text"]
        for section in page.get("logical_columns", [])
        for packet in original_column_context(section["source"]["header_scope"])
    )


def logical_column_declarations(page, page_source_id, *, identifier_lists):
    output = []
    for section in page.get("logical_columns", []):
        source, region_id = section["source"], section["region_id"]
        header = source["header_scope"]
        packets = original_column_context(header)
        args = original_column_title_args(header)
        role, _key = observed_role(packets, **args)
        texts = title_texts(packets, **args)
        raw = " ".join(packet["text"] for packet in packets)
        extent = column_body_extent(source)
        body = column_context_window(header)
        body[3] = extent["body_bottom"]
        diagrams = intersecting_source_diagrams(page["page_diagrams"], body)
        # This is a logical clipping window from the complete original header,
        # never an invented printed frame or a successful OCR word crop.
        title = [body[0], header["context_sources"][0]["bbox"][1], body[2], body[1]]
        output.append(
            {
                "source_region": proof_id(
                    {
                        "status": "observed_original_table_declaration",
                        "page_source": page_source_id,
                        "logical_column": region_id,
                    }
                ),
                "page_no": page["page_no"],
                "bbox": body,
                "role": role,
                "caption": {"text": " ".join(texts) if texts else raw, "bbox": title},
                "caption_sources": packets,
                "diagrams": diagrams,
                "identifier_lists": identifier_lists(body)
                if role == "compound" and not diagrams
                else [],
                "trusted_bottom": extent["trusted_bottom"],
                "unproved_boundaries": extent["unproved_boundaries"],
                "unproved_nonfinal_role": role in {"unknown", "unresolved"}
                and catalog_title_role(raw) in {"nonfinal", "mixed"},
                "unproved_title": role == "unresolved",
            }
        )
    return output
