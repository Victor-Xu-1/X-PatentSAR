"""Canonical serialization contract for SMILES stage output."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from patent_sar_extractor.contracts import (
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
) -> dict[str, Any]:
    return {
        **artifact_identity(SMILES_SCHEMA, SMILES_SCHEMA_VERSION),
        "execution_mode": execution_mode,
        "records": [dict(record) for record in records],
        "source_records": [dict(record) for record in source_records],
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
    if not isinstance(payload, dict):
        return []
    records = payload.get("source_records", [])
    if not isinstance(records, list) or any(
        not isinstance(row, dict) for row in records
    ):
        raise ValueError("Source recognition observations are malformed.")
    return records


def smiles_artifact_is_current(
    payload: Any, *, require_production: bool = True
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
    return (
        not require_production
        or payload.get("execution_mode") == PRODUCTION_SMILES_MODE
    )
