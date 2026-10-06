"""Source-catalog coverage and qualified records, independent of activity."""

from __future__ import annotations

from pathlib import Path

from patent_sar_extractor.contracts import (
    BINDINGS_SCHEMA,
    BINDINGS_SCHEMA_VERSION,
    artifact_identity_matches,
)

from .activity_identity import normalize_compound
from .catalog_reader import read_catalog_entries
from .pipeline_rules import annotate_binding_accuracy

SOURCE_EXECUTION_MODE = "production_structure_led"
FORMAL_SCOPE = "proved_printed_identifier_structure_corpus"


def proved_catalog(
    payload: dict, known_structures: set[str] | None = None
) -> list[dict]:
    if not isinstance(payload, dict):
        raise ValueError("Binding artifact must be an object")
    catalog, _ = read_catalog_entries(payload, known_structures)
    if catalog is None:
        raise ValueError("Formal binding requires the proved printed-ID catalog")
    return catalog


def binding_pairs(rows: list[dict], label_field: str = "cpd") -> list[tuple[str, str]]:
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("Formal records must be an ordered object list")
    if any(
        not isinstance(row.get(label_field), str)
        or not isinstance(row.get("structure_id"), str)
        for row in rows
    ):
        raise ValueError(
            "Formal record identifiers must be printed-label/image strings"
        )
    pairs = [
        (
            normalize_compound(row.get(label_field)).removeprefix("Compound "),
            str(row.get("structure_id") or ""),
        )
        for row in rows
    ]
    if any(not label or not image for label, image in pairs):
        raise ValueError("Formal records have missing printed-ID/image ownership")
    return pairs


def coverage_errors(payload: dict) -> list[str]:
    if not artifact_identity_matches(payload, BINDINGS_SCHEMA, BINDINGS_SCHEMA_VERSION):
        raise ValueError(
            "Binding artifact does not match the current source-led identity"
        )
    catalog = proved_catalog(payload)
    actual = binding_pairs(payload.get("final_bindings"))
    expected = binding_pairs(catalog)
    errors = []
    if payload.get("execution_mode") != SOURCE_EXECUTION_MODE:
        raise ValueError(
            "Bindings were not produced by the current source-led producer"
        )
    if payload["compound_catalog"].get("formal_acceptance_scope") != FORMAL_SCOPE:
        raise ValueError("Printed-ID catalog has an incompatible formal scope")
    if not expected:
        errors.append(
            "No proved printed-ID structure is available for formal processing."
        )
    if actual != expected:
        errors.append(
            "Formal binding order/coverage differs from the proved printed-ID catalog."
        )
    issues = payload.get("source_issues", [])
    if not isinstance(issues, list) or any(
        not isinstance(issue, (dict, str)) for issue in issues
    ):
        raise ValueError("Malformed binding source issues")
    if issues:
        errors.append(
            f"Original printed-ID ownership has {len(issues)} unresolved observations."
        )
    return errors


def image_exists(binding: dict, root: str = "") -> bool:
    return any(
        path and (Path(path).is_file() or (Path(root) / path).is_file())
        for path in (
            str(binding.get(field) or "")
            for field in ("display_image_path", "source_image_path", "image_path")
        )
    )


def confirmed_binding(binding: dict) -> bool:
    checked = annotate_binding_accuracy(dict(binding))
    return checked.get("accuracy_status") == "confirmed" and not checked.get(
        "fail_closed"
    )
