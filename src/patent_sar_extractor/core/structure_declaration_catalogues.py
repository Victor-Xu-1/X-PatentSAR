"""Existing original caption scopes bound declarations, never another reader."""

from .activity_context_geometry import grid_box, valid_box
from .caption_role_proof import caption_role_status
from .caption_role_semantics import catalog_title_role
from .cell_frame_proof import inside_box
from .source_body_context import intersecting_source_diagrams
from .source_evidence_identity import proof_id
from .source_geometry import overlaps
from .source_observations import project_source_observation
from .source_table_roles import title_texts
from .structure_catalogue_headers import header_catalogue_scope
from .structure_declaration_continuations import continued_catalogue_role
from .title_context_grids import caption_title_context


def catalogue_scopes_for_grids(
    page_no, grids, caption_roles, *, column_sections=(), original_pdf_sha256=None
):
    """Associate each identical physical frame once; retain its raw inventory."""
    headers = {}
    for section in column_sections:
        if section.get("role") != "structure_column_anchor":
            continue
        if section.get("page_no") != page_no:
            raise ValueError("Original numbered title belongs to another page")
        scope = header_catalogue_scope(section, original_pdf_sha256)
        if scope is None:
            continue
        box = tuple(scope["table_bbox"])
        if box in headers and headers[box] != scope:
            raise ValueError("Conflicting original numbered-header title owners")
        headers[box] = scope
    seen, scopes = {}, []
    for grid in grids:
        box = tuple(grid_box(grid))
        key = (page_no, box)
        observed = caption_roles is not None and key in caption_roles
        if not observed and box not in headers:
            continue
        if box in seen:
            if seen[box] != grid:
                raise ValueError(
                    "Duplicate original catalogue frame has conflicting original grid axes"
                )
            continue
        seen[box] = grid
        # An earlier observed catalogue remains the authority even if unresolved.
        # A later header may fill an absent owner, never vote over an old one.
        scopes.append(caption_roles[key] if observed else headers[box])
    return scopes


def validate_catalogue_scopes(source):
    scopes = source.get("catalogue_scopes", [])
    if not isinstance(scopes, list) or len(scopes) > 4096:
        raise ValueError("Malformed original declaration catalogue scopes")
    grids = {tuple(grid_box(grid)): grid for grid in source["page_grids"]}
    seen = set()
    for scope in scopes:
        if not isinstance(scope, dict):
            raise ValueError("Malformed original declaration catalogue owner")  # noqa: TRY004 -- shared source-schema boundary
        box = scope.get("table_bbox")
        if not isinstance(box, list) or not valid_box(box):
            reason = "invalid frame"
        elif tuple(box) in seen:
            reason = "duplicate frame"
        elif grids.get(tuple(box)) != scope.get("grid_axes"):
            reason = "grid axes mismatch"
        elif caption_role_status(scope, source["page_no"], box) is None:
            reason = "unreplayable caption role"
        elif scope["window"][2] != source["page_size"][0]:
            reason = "window width mismatch"
        else:
            reason = None
        if reason is not None:
            safe_box = box if reason != "invalid frame" else None
            raise ValueError(
                "Original catalogue differs from its complete page source: "
                f"{reason}; page {source['page_no']}; frame {safe_box}"
            )
        seen.add(tuple(box))
    return scopes


def catalogue_owns_caption(source, caption):
    """A raw nomination is covered only by its own retained physical source."""
    return any(
        overlaps(caption["bbox"], packet["bbox"])
        and inside_box(caption["bbox"], packet["bbox"])
        and caption["text"]
        == project_source_observation(packet, caption["bbox"])["text"]
        for scope in source.get("catalogue_scopes", [])
        for packet in scope["observations"]
    )


def catalogue_declarations(source, page_source_id, *, identifier_lists):
    output = []
    for scope in source.get("catalogue_scopes", []):
        role = caption_role_status(scope, source["page_no"], scope["table_bbox"])
        inherited = continued_catalogue_role(source, scope)
        if inherited is not None:
            role = inherited[0]
        body = list(scope["table_bbox"])
        diagrams = intersecting_source_diagrams(source["page_diagrams"], body)
        texts = title_texts(
            scope["observations"],
            contexts=scope["sources"],
            context=caption_title_context(scope),
        )
        raw = " ".join(packet["text"] for packet in scope["observations"])
        # This is the complete retained source window, not an invented word box.
        caption = {"text": " ".join(texts) if texts else raw, "bbox": scope["window"]}
        output.append(
            {
                "source_region": proof_id(
                    {
                        "status": "observed_original_table_declaration",
                        "page_source": page_source_id,
                        "caption_role": scope,
                    }
                ),
                "page_no": source["page_no"],
                "bbox": body,
                "role": role,
                "caption": caption,
                "caption_sources": scope["observations"],
                "diagrams": diagrams,
                "identifier_lists": identifier_lists(body)
                if role == "compound" and not diagrams
                else [],
                "trusted_bottom": body[3],
                "unproved_boundaries": [
                    {
                        "bbox": diagram["bbox"],
                        "identity": ["crossing_original_grid", diagram["id"]],
                    }
                    for diagram in diagrams
                    if not inside_box(diagram["bbox"], body)
                ],
                "unproved_nonfinal_role": role in {"unknown", "unresolved"}
                and catalog_title_role(raw) in {"nonfinal", "mixed"},
                "unproved_title": role == "unresolved",
                **({"continuation_source_region": inherited[1]} if inherited else {}),
            }
        )
    return output
