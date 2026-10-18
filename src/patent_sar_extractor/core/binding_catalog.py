"""Single numbered source catalog; activities are identifier-joined observations."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from patent_sar_extractor.contracts import (
    COMPOUND_CATALOG_SCHEMA,
    COMPOUND_CATALOG_SCHEMA_VERSION,
    schema_ref,
)

from .binding_labels import _binding_label_key
from .binding_source_claims import resolve_source_claims, source_candidate
from .identifier_order import natural_identifier_key
from .source_binding_proof import annotate_source_binding


def compound_catalog(
    primary: Sequence[dict[str, Any]],
    additional: Sequence[dict[str, Any]],
    *,
    source_issues: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    def checked_source(binding):
        checked = annotate_source_binding(dict(binding))
        if source_issues is not None and (
            checked.get("accuracy_status") != "confirmed" or checked.get("fail_closed")
        ):
            source_issues.append(
                {
                    "cpd": checked.get("cpd"),
                    "structure_id": checked.get("structure_id"),
                    "page_no": checked.get("page_no"),
                    "reason": "unproved_original_binding",
                    "evidence": {
                        "binding_rule": checked.get("binding_rule"),
                        "reasons": checked.get("evidence_reasons", []),
                        "proposal": dict(binding),
                    },
                }
            )
        return checked

    # Caller placement is not another ownership authority. Resolve the complete
    # proved collection with the SAME policy used by spatial capture/saved replay.
    candidates = []
    for binding in (*primary, *additional):
        checked = checked_source(binding)
        if (
            _binding_label_key(checked)
            and checked.get("accuracy_status") == "confirmed"
            and not checked.get("fail_closed")
        ):
            candidates.append(source_candidate(checked))
    claims = resolve_source_claims(candidates)
    if source_issues is not None:
        source_issues.extend(
            {
                "cpd": conflict.label_key,
                "page_no": conflict.page_index + 1,
                "reason": conflict.reason,
                "evidence": conflict.evidence,
            }
            for conflict in claims.conflicts
        )
    entries = {
        candidate.label_key: {**candidate.binding, "additional_sources": []}
        for candidate in claims.primary
    }
    seen = {candidate.structure_id for candidate in claims.primary}
    for candidate in claims.reprints:
        entries[candidate.label_key]["additional_sources"].append(
            dict(candidate.binding)
        )
        seen.add(candidate.structure_id)

    return {
        "schema": schema_ref(COMPOUND_CATALOG_SCHEMA, COMPOUND_CATALOG_SCHEMA_VERSION),
        "authority": "printed_identifier_and_original_spatial_evidence",
        "entries": [
            entries[key] for key in sorted(entries, key=natural_identifier_key)
        ],
        "numbered_compounds": len(entries),
        "source_observations": len(seen),
        "formal_acceptance_scope": "proved_printed_identifier_structure_corpus",
    }
