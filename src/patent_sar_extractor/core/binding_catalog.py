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
from .identifier_order import natural_identifier_key
from .pipeline_rules import annotate_binding_accuracy


def compound_catalog(
    primary: Sequence[dict[str, Any]], additional: Sequence[dict[str, Any]]
) -> dict[str, Any]:
    entries: dict[str, dict[str, Any]] = {}
    for binding in primary:
        checked = annotate_binding_accuracy(dict(binding))
        label = _binding_label_key(checked)
        if (
            label
            and checked.get("accuracy_status") == "confirmed"
            and not checked.get("fail_closed")
        ):
            if (
                label in entries
                and entries[label]["structure_id"] != checked["structure_id"]
            ):
                raise ValueError(
                    "Conflicting primary structures cannot share a printed compound ID"
                )
            entries.setdefault(label, {**checked, "additional_sources": []})
    seen = {str(binding["structure_id"]) for binding in entries.values()}
    for binding in additional:
        checked = annotate_binding_accuracy(dict(binding))
        label, structure_id = (
            _binding_label_key(checked),
            str(checked.get("structure_id") or ""),
        )
        if (
            label in entries
            and structure_id
            and structure_id not in seen
            and checked.get("accuracy_status") == "confirmed"
            and not checked.get("fail_closed")
        ):
            entries[label]["additional_sources"].append(checked)
            seen.add(structure_id)

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
