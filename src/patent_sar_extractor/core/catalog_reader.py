"""Recheck printed-ID ownership once for recognition and presentation consumers."""

from __future__ import annotations

from typing import Any

from patent_sar_extractor.contracts import (
    BINDINGS_SCHEMA,
    BINDINGS_SCHEMA_VERSION,
    COMPOUND_CATALOG_SCHEMA,
    COMPOUND_CATALOG_SCHEMA_VERSION,
    MAX_RECOGNITION_SOURCES,
    schema_ref,
    schema_ref_matches,
)

from .binding_records import binding_records
from .binding_source_claims import validate_catalog_claims
from .binding_source_references import reference_issues
from .pipeline_rules import _label_key, annotate_binding_accuracy
from .source_binding_proof import annotate_source_binding
from .title_geometry_memo import title_geometry_call

MAX_CATALOG_RECORDS = MAX_RECOGNITION_SOURCES


class CatalogValidationError(ValueError):
    """Invalid untrusted catalog value, including its serialized field types."""


def _checked_source(
    source: dict[str, Any], *, original_required=False, historical_review=False
) -> dict[str, Any]:
    candidates = source.get("visible_label_candidates", [])
    if (
        not isinstance(candidates, list)
        or len(candidates) > 1000
        or any(not isinstance(candidate, dict) for candidate in candidates)
    ):
        raise CatalogValidationError("Printed-ID label observations are invalid.")
    if historical_review:
        # Keep raw identity/geometry; do not run newer semantic proof algorithms
        # over archived evidence or let cached confirmation survive this view.
        return {
            **source,
            "accuracy_status": "needs_review",
            "evidence_tier": "unknown",
            "fail_closed": True,
        }
    try:
        return (
            annotate_source_binding(dict(source))
            if original_required
            else annotate_binding_accuracy(dict(source))
        )
    except (TypeError, ValueError, OverflowError, AttributeError) as exc:
        raise CatalogValidationError("Printed-ID source proof is malformed.") from exc


@title_geometry_call
def read_catalog_entries(
    payload: dict[str, Any],
    known_structures: set[str] | None = None,
    *,
    historical_review: bool = False,
) -> tuple[list[dict[str, Any]] | None, set[str]]:
    """Read current ownership, or explicitly unqualified historical raw records.

    Historical review retains bounded IDs/known image ownership and raw aliases,
    not scientific confirmation. Only the Web archive projection selects it;
    every scientific caller retains the strict default.
    """
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
    original_required = not historical_review and schema_ref_matches(
        payload.get("schema"), schema_ref(BINDINGS_SCHEMA, BINDINGS_SCHEMA_VERSION)
    )
    if original_required:
        try:
            entries = binding_records(payload)
        except ValueError as exc:
            raise CatalogValidationError(str(exc)) from exc
    for raw in entries:
        if not isinstance(raw, dict):
            raise CatalogValidationError("Printed-ID catalog row is invalid.")
        checked = _checked_source(
            raw,
            original_required=original_required,
            historical_review=historical_review,
        )
        key = _label_key(str(checked.get("cpd") or checked.get("compound_id") or ""))
        structure_id = str(checked.get("structure_id") or "")
        if (
            not key
            or key in labels
            or not structure_id
            or (known_structures is not None and structure_id not in known_structures)
            or structure_id in owned
            or (
                not historical_review
                and (
                    checked.get("accuracy_status") != "confirmed"
                    or checked.get("fail_closed")
                )
            )
        ):
            raise CatalogValidationError(
                "Primary ID/crop ownership is not independently confirmed."
            )
        labels.add(key)
        owned.add(structure_id)
        additional = checked.get("additional_sources", [])
        if not isinstance(additional, list) or len(additional) > 1000:
            raise CatalogValidationError("Additional source collection is invalid.")
        checked_additional = []
        for source in additional:
            if not isinstance(source, dict):
                raise CatalogValidationError("Additional source is invalid.")
            proof = _checked_source(
                source,
                original_required=original_required,
                historical_review=historical_review,
            )
            alias = str(proof.get("structure_id") or "")
            if (
                _label_key(str(proof.get("cpd") or proof.get("compound_id") or ""))
                != key
                or not alias
                or (known_structures is not None and alias not in known_structures)
                or alias in owned
                or (
                    not historical_review
                    and (
                        proof.get("accuracy_status") != "confirmed"
                        or proof.get("fail_closed")
                    )
                )
            ):
                raise CatalogValidationError(
                    "Reprint does not prove the same printed owner."
                )
            owned.add(alias)
            alias_ids.add(alias)
            checked_additional.append(proof)
            if len(owned) > MAX_CATALOG_RECORDS:
                raise CatalogValidationError(
                    "Catalog source observations exceed their bound."
                )
        checked["additional_sources"] = checked_additional
        output.append(checked)
    if original_required:
        try:
            validate_catalog_claims(output)
        except (TypeError, ValueError, KeyError, AttributeError) as exc:
            raise CatalogValidationError(
                "Original source claims are inconsistent."
            ) from exc
    try:
        # Partial proved structures remain available for review. Completeness
        # is rechecked independently by formal_structure, never saved flags.
        if not historical_review:
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
