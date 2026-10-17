"""Recheck printed-ID ownership once for recognition and presentation consumers."""

from __future__ import annotations

from typing import Any

from patent_sar_extractor.contracts import (
    BINDINGS_SCHEMA,
    BINDINGS_SCHEMA_VERSION,
    COMPOUND_CATALOG_SCHEMA,
    COMPOUND_CATALOG_SCHEMA_VERSION,
    schema_ref,
    schema_ref_matches,
)

from .binding_source_references import reference_issues
from .pipeline_rules import _label_key, annotate_binding_accuracy
from .source_binding_proof import annotate_source_binding

MAX_CATALOG_RECORDS = 25000


class CatalogValidationError(ValueError):
    """Invalid untrusted catalog value, including its serialized field types."""


def _checked_source(
    source: dict[str, Any], *, original_required=False
) -> dict[str, Any]:
    candidates = source.get("visible_label_candidates", [])
    if (
        not isinstance(candidates, list)
        or len(candidates) > 1000
        or any(not isinstance(candidate, dict) for candidate in candidates)
    ):
        raise CatalogValidationError("Printed-ID label observations are invalid.")
    try:
        return (
            annotate_source_binding(dict(source))
            if original_required
            else annotate_binding_accuracy(dict(source))
        )
    except (TypeError, ValueError, OverflowError, AttributeError) as exc:
        raise CatalogValidationError("Printed-ID source proof is malformed.") from exc


def read_catalog_entries(
    payload: dict[str, Any], known_structures: set[str] | None = None
) -> tuple[list[dict[str, Any]] | None, set[str]]:
    catalog = payload.get("compound_catalog")
    if catalog is None:
        return None, set()
    if (
        not isinstance(catalog, dict)
        or catalog.get("schema")
        != schema_ref(COMPOUND_CATALOG_SCHEMA, COMPOUND_CATALOG_SCHEMA_VERSION)
        or type(catalog["schema"]["version"]) is not int
        or catalog.get("authority")
        != "printed_identifier_and_original_spatial_evidence"
    ):
        raise CatalogValidationError("Printed-ID catalog identity is not supported.")
    entries = catalog.get("entries")
    if not isinstance(entries, list) or len(entries) > MAX_CATALOG_RECORDS:
        raise CatalogValidationError(
            "Printed-ID catalog entries are missing or excessive."
        )
    labels, owned, alias_ids = set(), set(), set()
    output = []
    original_required = schema_ref_matches(
        payload.get("schema"), schema_ref(BINDINGS_SCHEMA, BINDINGS_SCHEMA_VERSION)
    )
    for raw in entries:
        if not isinstance(raw, dict):
            raise CatalogValidationError("Printed-ID catalog row is invalid.")
        checked = _checked_source(raw, original_required=original_required)
        key = _label_key(str(checked.get("cpd") or checked.get("compound_id") or ""))
        structure_id = str(checked.get("structure_id") or "")
        if (
            not key
            or key in labels
            or not structure_id
            or (known_structures is not None and structure_id not in known_structures)
            or structure_id in owned
            or checked.get("accuracy_status") != "confirmed"
            or checked.get("fail_closed")
        ):
            raise CatalogValidationError(
                "Primary ID/crop ownership is not independently confirmed."
            )
        labels.add(key)
        owned.add(structure_id)
        additional = checked.get("additional_sources", [])
        if not isinstance(additional, list) or len(additional) > 1000:
            raise CatalogValidationError("Additional source collection is invalid.")
        for source in additional:
            if not isinstance(source, dict):
                raise CatalogValidationError("Additional source is invalid.")
            proof = _checked_source(source, original_required=original_required)
            alias = str(proof.get("structure_id") or "")
            if (
                _label_key(str(proof.get("cpd") or proof.get("compound_id") or ""))
                != key
                or not alias
                or (known_structures is not None and alias not in known_structures)
                or alias in owned
                or proof.get("accuracy_status") != "confirmed"
                or proof.get("fail_closed")
            ):
                raise CatalogValidationError(
                    "Reprint does not prove the same printed owner."
                )
            owned.add(alias)
            alias_ids.add(alias)
            if len(owned) > MAX_CATALOG_RECORDS:
                raise CatalogValidationError(
                    "Catalog source observations exceed their bound."
                )
        output.append(checked)
    try:
        # Partial proved structures remain available for review. Completeness
        # is rechecked independently by formal_structure, never saved flags.
        reference_issues(
            payload,
            output,
            required=original_required,
        )
    except (TypeError, ValueError, KeyError) as exc:
        raise CatalogValidationError(
            "Original source-reference proof is malformed."
        ) from exc
    return output, alias_ids
