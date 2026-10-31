"""Canonical continuation identities partition only already validated ancestry."""

from patent_sar_extractor.artifact_nodes import MAX_ARTIFACT_BYTES

from .caption_role_links import MAX_CONTINUATION_DEPTH
from .composite_source_identity import composite_source_digest
from .source_evidence_identity import MAX_SOURCE_REGION_BYTES, SourceEvidenceLimit


def caption_ancestry_partitions(scope, prefix, *, component_limit):
    """Bound every local original fact; only the prior-page link is an inventory.

    Callers still own semantic/source validation. This cannot grant a role,
    erase a previous page or allow an oversized local source through its limit.
    """
    partitions, seen = set(), set()
    for _depth in range(MAX_CONTINUATION_DEPTH + 1):
        if not isinstance(scope, dict) or id(scope) in seen:
            raise ValueError("Invalid original caption ancestry")
        seen.add(id(scope))
        local = dict(scope)
        link = scope.get("continuation")
        if link is not None:
            if not isinstance(link, dict) or "previous" not in link:
                raise ValueError("Missing original caption ancestor")
            local["continuation"] = {**link, "previous": None}
        # Shallow copies share every original observation. The prior-page
        # reference alone is replaced for this local SIZE check, never hashing.
        composite_source_digest(
            local,
            set(),
            maximum=component_limit,
            component_limit=component_limit,
            label=f"caption local source at ancestry depth {_depth}",
        )
        partitions.add(prefix)
        if link is None:
            return partitions
        prefix = (*prefix, "continuation")
        partitions.add(prefix)
        prefix = (*prefix, "previous")
        scope = link["previous"]
    raise SourceEvidenceLimit("Original caption ancestry exceeds its depth budget")


def catalogue_declaration_id(page_source_id, scope):
    """Same canonical bytes as the old short-region identity, complete ancestry."""
    partitions = {()}
    partitions.update(
        caption_ancestry_partitions(
            scope,
            ("caption_role",),
            component_limit=MAX_SOURCE_REGION_BYTES,
        )
    )
    return composite_source_digest(
        {
            "status": "observed_original_table_declaration",
            "page_source": page_source_id,
            "caption_role": scope,
        },
        partitions,
        maximum=MAX_ARTIFACT_BYTES,
        component_limit=MAX_SOURCE_REGION_BYTES,
        label="catalogue declaration",
    )
