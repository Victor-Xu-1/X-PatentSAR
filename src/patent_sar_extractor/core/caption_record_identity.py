"""Bound original caption ancestry inside an explicitly owned evidence wrapper."""

from patent_sar_extractor.artifact_nodes import MAX_ARTIFACT_BYTES

from .caption_role_identity import caption_ancestry_partitions
from .composite_source_identity import composite_source_digest
from .source_evidence_identity import MAX_SOURCE_REGION_BYTES, proof_id


def caption_record_id(record, scope_paths):
    """Preserve exact canonical bytes; never find or split arbitrary nested data.

    Only caller-declared caption-role paths may expose prior-page inventories.
    The WHOLE local wrapper, including every current role and link metadata,
    still fits one original region. Every ancestor keeps that same local limit.
    Semantic/source admission remains with the existing independent validators.
    """
    if not isinstance(record, dict):
        return proof_id(record)
    local = dict(record)
    partitions = set()
    for path in scope_paths:
        scope = record
        for field in path:
            scope = scope.get(field) if isinstance(scope, dict) else None
        if not isinstance(scope, dict) or scope.get("continuation") is None:
            continue
        partitions.update(
            caption_ancestry_partitions(
                scope, path, component_limit=MAX_SOURCE_REGION_BYTES
            )
        )
        partitions.update(path[:depth] for depth in range(len(path)))
        current = local
        for field in path[:-1]:
            current[field] = dict(current[field])
            current = current[field]
        current[path[-1]] = {
            **scope,
            "continuation": {**scope["continuation"], "previous": None},
        }
    # Unknown fields and the combined local envelope cannot use ancestry's
    # inventory permission to evade the unchanged one-MiB region limit.
    local_identity = proof_id(local)
    if not partitions:
        return local_identity
    return composite_source_digest(
        record,
        partitions,
        maximum=MAX_ARTIFACT_BYTES,
        component_limit=MAX_SOURCE_REGION_BYTES,
        label="caption evidence inventory",
    )
