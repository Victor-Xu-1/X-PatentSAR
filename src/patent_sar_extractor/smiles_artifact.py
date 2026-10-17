"""Canonical serialization contract for SMILES stage output."""

from __future__ import annotations

from collections.abc import Iterable
from itertools import islice
from typing import Any

from patent_sar_extractor.contracts import (
    MAX_RECOGNITION_SOURCES,
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
) -> dict[str, Any]:
    groups = {}
    remaining = MAX_RECOGNITION_SOURCES
    for field, source in (
        ("records", records),
        ("source_records", source_records),
        ("reprint_records", reprint_records),
    ):
        rows = list(islice(source, remaining + 1))
        if len(rows) > remaining or any(not isinstance(row, dict) for row in rows):
            raise ValueError(
                "Recognition source collection is malformed or exceeds its bound."
            )
        groups[field] = [dict(row) for row in rows]
        remaining -= len(rows)
    return {
        **artifact_identity(SMILES_SCHEMA, SMILES_SCHEMA_VERSION),
        "execution_mode": execution_mode,
        **groups,
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
    if not isinstance(payload.get("reprint_records"), list) or any(
        not isinstance(row, dict) for row in payload["reprint_records"]
    ):
        return False
    if (
        sum(
            len(payload.get(field, []))
            for field in ("records", "source_records", "reprint_records")
        )
        > MAX_RECOGNITION_SOURCES
    ):
        return False
    return (
        not require_production
        or payload.get("execution_mode") == PRODUCTION_SMILES_MODE
    )
