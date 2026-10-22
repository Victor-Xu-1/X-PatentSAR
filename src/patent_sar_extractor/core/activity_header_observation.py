"""One final physical-column header authority with immutable source evidence."""

from dataclasses import replace

from .activity_context_geometry import context_floor
from .activity_grid_context import _prefix
from .activity_header_columns import observe_header_columns
from .activity_header_identity import (
    compact_header,
    context_conflict,
    header_conflict,
    schema_requires_review,
)
from .activity_header_layout import discover_header_layout, header_bounds
from .activity_header_pair import observe_header_pair
from .activity_header_proof import valid_header_proof
from .activity_header_sources import (
    capture_header_sources,
    header_source_conflicts,
    select_header_context,
    source_context_region,
)
from .activity_headers import context_from_text, grid_schema
from .activity_models import GridSchema
from .source_geometry import native_region
from .table_geometry import ocr_tokens_with_positions
from .text_ocr import configuration


def refine_scanned_header(
    page, region: dict, original: GridSchema | None, *, tokens=(), evidence_sink=None
) -> GridSchema | None:
    """Discover missing roles if needed, then prove every field in its own column.

    Missing initial schemas require complete proof; known schemas keep unresolved
    columns/source identities as review. Neither matching resolutions nor high
    confidence establishes chemical/scientific correctness on its own.
    """
    band = (
        (region["xs"][0], region["ys"][0], region["xs"][-1], region["ys"][-1])
        if region.get("xs") and region.get("ys")
        else (0, 0, page.rect.width, page.rect.height)
    )
    if native_region(tokens, band, bool(page.get_text("words"))) or (
        original is not None
        and type(original.first_data_row) is int
        and original.first_data_row == 0
    ):
        return original
    bounds = header_bounds(page, region, original)
    if bounds is None:
        proof = {
            "status": "unresolved",
            "reason": "unsupported_header_bounds",
            "observations": [],
        }
        if evidence_sink is not None:
            evidence_sink.append(proof)
        return replace(original, header_resolution=proof) if original else None
    limit, discovery_bounds = bounds
    discovery = ()
    source = original
    if source is None or (
        schema_requires_review(source)
        and configuration.get_auxiliary_text_runtime() is not None
    ):
        if source is not None:
            expanded = header_bounds(page, region, None)
            if expanded is None:
                expanded = bounds
            discovery_limit, discovery_bounds = expanded
        else:
            discovery_limit = limit
        layout = discover_header_layout(
            page, region, discovery_bounds, discovery_limit, tokens=tokens
        )
        discovery = layout.observations
        source = layout.schema or source
        if source is not None:
            limit = source.first_data_row
    captured_sources = capture_header_sources(page, region, limit, tokens)
    prefix_region = region
    if captured_sources is not None:
        prefix_region = source_context_region(
            captured_sources,
            [region["xs"][0], region["ys"][0], region["xs"][-1], region["ys"][limit]],
        )
        if prefix_region is None:
            raise ValueError("Malformed original header context window")
    floor = (
        context_floor(region["context_geometry"]) if "context_geometry" in region else 0
    )
    prefix_bounds = (
        0,
        max(0, floor, region["ys"][0] - 80),
        page.rect.width,
        region["ys"][0],
    )
    observations, candidates, verified = [], [], []
    resolved_context = None

    def resolution(status, **extra):
        evidence = {
            "column_contract": 5 if captured_sources is not None else 1,
            "status": status,
            "original_headers": list(original.raw_headers) if original else [],
            "original_context": original.context.raw_context if original else "",
            "discovery_observations": list(discovery),
            "observations": observations,
            "header_band_bbox": [
                region["xs"][0],
                region["ys"][0],
                region["xs"][-1],
                region["ys"][limit],
            ],
            **(
                {"original_source": captured_sources}
                if captured_sources is not None
                else {}
            ),
            **(
                {"resolved_context": resolved_context.raw_context}
                if resolved_context is not None
                else {}
            ),
            **extra,
        }
        if evidence_sink is not None:
            evidence_sink.append(evidence)
        return evidence

    def unresolved(reason):
        proof = resolution("unresolved", reason=reason)
        return replace(original, header_resolution=proof) if original else None

    if source is None:
        return unresolved("unproved_header_roles")
    if len(source.raw_headers) != len(region["xs"]) - 1:
        return unresolved("header_column_count_mismatch")
    paired_columns = observe_header_pair(
        page, region, limit, tokens, observe_header_columns
    )
    for dpi, columns in zip((400, 600), paired_columns):
        prefix_tokens = ocr_tokens_with_positions(page, dpi=dpi, bounds=prefix_bounds)
        prefix = _prefix(prefix_tokens, prefix_region)
        candidate = grid_schema(context_from_text(prefix, prefix), columns.matrix)
        observations.append(
            {
                "method": f"header_ocr_{dpi}dpi",
                "bbox": list(prefix_bounds),
                "matrix": columns.matrix,
                "prefix": prefix,
                "columns": list(columns.columns),
            }
        )
        verified.append(columns.verified)
        if candidate is None or candidate.first_data_row != limit:
            return unresolved("unproved_header_boundary")
        candidates.append(candidate)
    first, second = candidates
    identifiers = tuple(g.id_column for g in source.groups)
    if any(
        tuple(g.id_column for g in candidate.groups) != identifiers
        for candidate in candidates
    ):
        return unresolved("conflicting_identifier_columns")
    band = [region["xs"][0], region["ys"][0], region["xs"][-1], region["ys"][limit]]
    source_checks = (
        [
            header_source_conflicts(
                captured_sources,
                band,
                list(original.raw_headers) if original else [],
                original.context.raw_context if original else "",
                candidate,
            )
            for candidate in candidates
        ]
        if captured_sources is not None
        else []
    )
    if source_checks and any(check is None for check in source_checks):
        return unresolved("invalid_original_source_scope")
    conflicts = [
        (
            any(check[0][i] for check in source_checks)
            if source_checks
            else any(
                header_conflict(old, candidate.raw_headers[i])
                for candidate in candidates
            )
        )
        or any(
            header_conflict(column.get("native_text", ""), candidate.raw_headers[i])
            for observed, candidate in zip(observations, candidates)
            for column in observed["columns"]
            if column["physical_column"] == i
        )
        for i, old in enumerate(source.raw_headers)
    ]
    agreed = [
        compact_header(a) == compact_header(b)
        and all(v[i] for v in verified)
        and not conflicts[i]
        for i, (a, b) in enumerate(zip(first.raw_headers, second.raw_headers))
    ]
    caption_conflict = (
        any(check[1] for check in source_checks)
        if source_checks
        else any(context_conflict(source.context, c.context) for c in candidates)
    )
    caption_proved = (
        bool(first.context.table_id) or captured_sources is not None
    ) and compact_header(first.context.raw_caption) == compact_header(
        second.context.raw_caption
    )
    if original is None and (not all(agreed) or not caption_proved or caption_conflict):
        proof = resolution(
            "unresolved",
            reason="incomplete_initial_header_proof",
            conflicting_columns=[i for i, c in enumerate(conflicts) if c],
            context_conflict=caption_conflict,
        )
        return None
    headers = tuple(
        first.raw_headers[i] if ok else source.raw_headers[i]
        for i, ok in enumerate(agreed)
    )
    context = (
        first.context if caption_proved and not caption_conflict else source.context
    )
    if caption_proved and not caption_conflict and captured_sources is not None:
        resolved_context = select_header_context(captured_sources, band, first.context)
        if resolved_context is None:
            return unresolved("disjoint_qualified_context")
        context = resolved_context
    selected = grid_schema(context, [list(headers)])
    if selected is None:
        return unresolved("unproved_resolved_header")
    complete = all(agreed) and not caption_conflict
    proof = resolution(
        "observed_header_consensus" if complete else "unresolved",
        conflicting_columns=[i for i, c in enumerate(conflicts) if c],
        unverified_columns=[i for i, ok in enumerate(agreed) if not ok],
        context_conflict=caption_conflict,
    )
    if complete and not valid_header_proof(proof):
        proof.update(status="unresolved", reason="column_proof_replay_failed")
    return replace(selected, first_data_row=limit, header_resolution=proof)
