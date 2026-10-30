"""Explicit catalogue/column/declaration title owners in the existing ledger."""

from .binding_records import binding_records
from .caption_role_links import MAX_CONTINUATION_DEPTH
from .cell_frame_proof import inside_box
from .source_observations import project_source_observation
from .text_ocr.source_inventory import MAX_SOURCE_CELLS
from .title_context_source import (
    TITLE_CONTEXT,
    original_title_raw_owner,
    title_context_id,
    valid_title_context,
)
from .title_source_proof import (
    MAX_TITLE_SOURCES,
    TITLE_SOURCES,
    raw_title_packet,
    source_title_geometry,
    source_title_id,
)


def _caption_parents(role):
    depth = 0
    while role is not None:
        if not isinstance(role, dict) or depth > MAX_CONTINUATION_DEPTH:
            raise ValueError("Malformed original title role ancestry")
        sources = role.get("sources")
        if not isinstance(sources, list) or not 1 <= len(sources) <= 2:
            raise ValueError("Missing original title role sources")
        yield from sources
        link = role.get("continuation")
        if link is not None and (
            not isinstance(link, dict) or not isinstance(link.get("previous"), dict)
        ):
            raise ValueError("Malformed original title continuation owner")
        role = link["previous"] if link is not None else None
        depth += 1


def _parents(payload):
    if not isinstance(payload, dict):
        raise TypeError("Malformed original title ledger")
    for row in binding_records(payload, legacy=True):
        additional = row.get("additional_sources", [])
        if not isinstance(additional, list) or len(additional) > 1000:
            raise ValueError("Malformed original title reprints")
        for binding in (row, *additional):
            if not isinstance(binding, dict):
                raise TypeError("Malformed original title binding owner")
            evidence = binding.get("exact_caption_evidence")
            if evidence is None:
                continue
            if not isinstance(evidence, dict) or not isinstance(
                evidence.get("ownership", {}), dict
            ):
                raise TypeError("Malformed original title caption owner")
            owner = evidence.get("ownership", {})
            yield from _caption_parents(owner.get("caption_role"))
            boundary = owner.get("page_boundary")
            if isinstance(boundary, dict):
                yield from _caption_parents(boundary.get("other_role"))
    sections = payload.get("source_sections", [])
    if not isinstance(sections, list):
        raise TypeError("Malformed original title section inventory")
    for section in sections:
        if not isinstance(section, dict):
            raise TypeError("Malformed original title section")
        role = section.get("role")
        if role == "nonfinal_caption_catalog":
            yield from _caption_parents(section.get("caption_role"))
        elif role in {"structure_column_anchor", "unruled_structure_region"}:
            source = section.get("source")
            header = source.get("header_scope") if isinstance(source, dict) else None
            if not isinstance(header, dict):
                raise ValueError("Missing original title column owner")
            header = header.get("anchor_scope", header)
            if header is not None:
                if not isinstance(header, dict) or not isinstance(
                    header.get("context_sources"), list
                ):
                    raise ValueError("Malformed original title column context")
                yield from header["context_sources"]
        elif role == "structure_declaration_page":
            source = section.get("source")
            chunks = source.get("page_context") if isinstance(source, dict) else None
            if not isinstance(chunks, list):
                raise ValueError("Missing original title declaration owner")
            for chunk in chunks:
                if not isinstance(chunk, dict) or not isinstance(
                    chunk.get("sources"), list
                ):
                    raise TypeError("Malformed original title declaration context")
                yield from chunk["sources"]
            catalogues = source.get("catalogue_scopes", [])
            if not isinstance(catalogues, list) or len(catalogues) > 4096:
                raise ValueError("Malformed original declaration title scopes")
            for catalogue in catalogues:
                yield from _caption_parents(catalogue)
            columns = source.get("logical_columns", [])
            if not isinstance(columns, list) or len(columns) > 4096:
                raise ValueError("Malformed original declaration logical title scopes")
            for column in columns:
                yield from column["source"]["header_scope"]["context_sources"]
    observations = payload.get("source_role_observations", {})
    if not isinstance(observations, dict):
        raise TypeError("Malformed original title observation ledger")
    for item in observations.values():
        if not isinstance(item, dict):
            raise TypeError("Malformed original title observation")
        if item.get("kind") == "binding_proposal":
            proposal = item.get("proposal")
            if not isinstance(proposal, dict):
                raise ValueError("Malformed original title proposal")
            yield from _caption_parents(proposal.get("caption_role"))


def title_source_cells(payload):
    seen = set()
    for parent in _parents(payload):
        if not valid_title_context(parent):
            raise ValueError("Malformed original title parent")
        context = parent[TITLE_CONTEXT]
        context_key = title_context_id(context)
        if context_key not in seen:
            seen.add(context_key)
            if len(seen) > MAX_SOURCE_CELLS:
                raise ValueError("Original title contexts exceed their source bound")
            yield (
                context["page_no"],
                {"method": "original_title_context", "title_context": context},
            )
        records = parent.get(TITLE_SOURCES, [])
        if not isinstance(records, list) or len(records) > MAX_TITLE_SOURCES:
            raise ValueError("Malformed original title witness inventory")
        for record in records:
            if source_title_geometry(record) is None:
                raise ValueError("Malformed original title source")
            nomination = record["nomination_source"]
            raw_owner = original_title_raw_owner(parent, record)
            if (
                not isinstance(raw_owner, dict)
                or parent.get("origin") != nomination["origin"]
                or not inside_box(nomination["bbox"], raw_owner.get("bbox"))
                or raw_title_packet(
                    project_source_observation(raw_owner, nomination["bbox"])
                )
                != nomination
            ):
                raise ValueError("Original title witness has no raw parent owner")
            key = source_title_id(record)
            if key in seen:
                continue
            seen.add(key)
            if len(seen) > MAX_SOURCE_CELLS:
                raise ValueError("Original title witnesses exceed their source bound")
            yield (
                record["page_no"],
                {"method": "original_title", "title_source": record},
            )


def validate_title_page_inventory(payload, pages):
    """All saved title owners use the existing complete declaration page source."""
    originals = {section["page_no"]: section["source"] for section in pages}

    def axes_key(grids):
        return sorted((tuple(grid["xs"]), tuple(grid["ys"])) for grid in grids)

    for page_no, cell in title_source_cells(payload):
        if cell["method"] != "original_title_context":
            continue
        context = cell["title_context"]
        ink = context["ink_source"]
        if ink is None or "parallel_grids" not in ink["context"]:
            continue
        original = originals.get(page_no)
        if (
            original is None
            or original["page_size"] != context["page_size"]
            or axes_key(original["page_grids"])
            != axes_key(ink["context"]["page_grids"])
        ):
            raise ValueError(
                "Original title family changed the complete page grid inventory"
            )
