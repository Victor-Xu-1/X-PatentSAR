"""Canonical serialization contract for SMILES stage output."""

from __future__ import annotations

from collections.abc import Iterable
from itertools import islice
from typing import Any

from patent_sar_extractor.contracts import (
    MAX_RECOGNITION_SOURCES,
    OCSR_RECOGNITION_SCOPE,
    SMILES_SCHEMA,
    SMILES_SCHEMA_VERSION,
    artifact_identity,
    artifact_identity_matches,
)

PRODUCTION_SMILES_MODE = "production_decimer"
DIAGNOSTIC_SMILES_MODE = "diagnostic_unvalidated"


def build_smiles_artifact(
    records: Iterable[dict[str, Any]],
    *,
    execution_mode: str = PRODUCTION_SMILES_MODE,
    source_records: Iterable[dict[str, Any]] = (),
    reprint_records: Iterable[dict[str, Any]] = (),
    candidate_records: Iterable[dict[str, Any]] = (),
    candidate_inventory: dict[str, Any] | None = None,
) -> dict[str, Any]:
    groups = {}
    remaining = MAX_RECOGNITION_SOURCES
    for field, source in (
        ("records", records),
        ("source_records", source_records),
        ("reprint_records", reprint_records),
        ("candidate_records", candidate_records),
    ):
        rows = list(islice(source, remaining + 1))
        if len(rows) > remaining or any(not isinstance(row, dict) for row in rows):
            raise ValueError(
                "Recognition source collection is malformed or exceeds its bound."
            )
        groups[field] = [dict(row) for row in rows]
        remaining -= len(rows)
    _validate_candidate_group(groups, candidate_inventory)
    return {
        **artifact_identity(SMILES_SCHEMA, SMILES_SCHEMA_VERSION),
        "execution_mode": execution_mode,
        **groups,
        "candidate_inventory": candidate_inventory,
        "recognition_input_scope": OCSR_RECOGNITION_SCOPE
        if candidate_inventory is not None
        else "proved_sources_only",
        "formal_acceptance_scope": "proved_printed_identifier_structure_corpus",
    }


def smiles_records(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    records = payload.get("records")
    if not isinstance(records, list):
        return []
    return [record for record in records if isinstance(record, dict)]


def smiles_source_records(payload: Any) -> list[dict[str, Any]]:
    return _source_records(payload, "source_records")


def smiles_reprint_records(payload: Any) -> list[dict[str, Any]]:
    return _source_records(payload, "reprint_records")


def smiles_candidate_records(payload: Any) -> list[dict[str, Any]]:
    return _source_records(payload, "candidate_records")


def smiles_observations(payload: Any) -> list[dict[str, Any]]:
    """Recognized numbered sources; deferred inventory is not model execution."""
    return [
        *smiles_records(payload),
        *smiles_source_records(payload),
        *smiles_reprint_records(payload),
    ]


def _validate_candidate_group(groups, inventory):
    from .core.ocsr.candidate_scope import (
        validate_inventory_records,
    )

    if inventory is None:
        if groups["candidate_records"]:
            raise ValueError(
                "Unassigned observations require a complete original inventory"
            )
        return
    validate_inventory_records(inventory, groups)


def _source_records(payload: Any, field: str) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    records = payload.get(field, [])
    if (
        not isinstance(records, list)
        or len(records) > MAX_RECOGNITION_SOURCES
        or any(not isinstance(row, dict) for row in records)
    ):
        raise ValueError("Source recognition observations are malformed.")
    return records


def smiles_artifact_is_current(
    payload: Any,
    *,
    require_production: bool = True,
    require_all_candidates: bool = False,
) -> bool:
    if not artifact_identity_matches(payload, SMILES_SCHEMA, SMILES_SCHEMA_VERSION):
        return False
    if not isinstance(payload.get("records"), list) or any(
        not isinstance(row, dict) for row in payload["records"]
    ):
        return False
    if not isinstance(payload.get("source_records", []), list) or any(
        not isinstance(row, dict) for row in payload.get("source_records", [])
    ):
        return False
    if not isinstance(payload.get("reprint_records"), list) or any(
        not isinstance(row, dict) for row in payload["reprint_records"]
    ):
        return False
    if (
        not isinstance(payload.get("candidate_records"), list)
        or any(not isinstance(row, dict) for row in payload["candidate_records"])
        or "candidate_inventory" not in payload
    ):
        return False
    if (
        sum(
            len(payload.get(field, []))
            for field in (
                "records",
                "source_records",
                "reprint_records",
                "candidate_records",
            )
        )
        > MAX_RECOGNITION_SOURCES
    ):
        return False
    try:
        _validate_candidate_group(payload, payload["candidate_inventory"])
    except (ValueError, TypeError, KeyError, OverflowError):
        return False
    expected_scope = (
        OCSR_RECOGNITION_SCOPE
        if payload["candidate_inventory"] is not None
        else "proved_sources_only"
    )
    if (
        payload.get("recognition_input_scope") != expected_scope
        or require_all_candidates
        and payload["candidate_inventory"] is None
    ):
        return False
    return (
        not require_production
        or payload.get("execution_mode") == PRODUCTION_SMILES_MODE
    )
