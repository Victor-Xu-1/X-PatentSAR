"""Content-addressed header proof in the existing activity artifact, not a cache.

Rows retain their cell evidence and a small header reference. Full observations,
including rejected layouts without rows, are stored once and checked on read.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import fields

from patent_sar_extractor.contracts import (
    ACTIVITY_SCHEMA,
    ACTIVITY_SCHEMA_VERSION,
    schema_ref,
    schema_ref_matches,
)

from .activity_context_geometry import validate_header_context_geometry
from .activity_header_identity import detector_header_conflict
from .activity_header_proof import valid_header_proof
from .activity_models import ActivityRow
from .cell_header_proof import physical_header_valid

_SUMMARY_FIELDS = (
    "status",
    "reason",
    "conflicting_columns",
    "unverified_columns",
    "context_conflict",
)


def proof_id(proof: dict) -> str:
    if not isinstance(proof, dict) or not isinstance(proof.get("status"), str):
        raise TypeError("Malformed original header evidence")
    encoded = json.dumps(
        proof,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    if len(encoded) > 1024 * 1024:
        raise ValueError("Original header evidence exceeds its bounded region limit")
    return hashlib.sha256(encoded).hexdigest()


def _reference(key: str, proof: dict) -> dict:
    return {
        "evidence_ref": key,
        **{name: proof[name] for name in _SUMMARY_FIELDS if name in proof},
    }


def serialize_header_evidence(
    rows: list[ActivityRow], observations: list[dict]
) -> tuple[list[dict], dict[str, dict]]:
    catalog, identities = {}, {}

    def intern(proof):
        # Call-local object identity only saves repeated hashing; the persisted
        # identity is always the content digest, never a process object ID.
        identity = id(proof)
        if identity not in identities:
            key = proof_id(proof)
            identities[identity] = key
            catalog[key] = proof
        return identities[identity]

    for proof in observations:
        intern(proof)
    serialized = []
    for row in rows:
        # Avoid asdict recursively copying the same full OCR proof per row.
        record = {item.name: getattr(row, item.name) for item in fields(row)}
        sources = []
        for source in row.activity_sources:
            saved = dict(source)
            if "header_resolution" in source:
                proof = source["header_resolution"]
                saved["header_resolution"] = _reference(intern(proof), proof)
            sources.append(saved)
        serialized.append({**record, "activity_sources": sources})
    return serialized, catalog


def validate_header_evidence(payload: dict) -> list[str]:
    """Reject missing/tampered references; unresolved scientific proof stays open."""
    catalog = payload.get("header_observations", {})
    if not isinstance(catalog, dict) or len(catalog) > 25000:
        raise ValueError("Malformed original header evidence catalog")
    for key, proof in catalog.items():
        if key != proof_id(proof):
            raise ValueError("Original header evidence identity differs")
        validate_header_context_geometry(
            proof, (payload.get("coverage") or {}).get("regions")
        )
        if proof["status"] == "observed_header_consensus":
            if (
                "column_contract" in proof
                or schema_ref_matches(
                    payload.get("schema"),
                    schema_ref(ACTIVITY_SCHEMA, ACTIVITY_SCHEMA_VERSION),
                )
            ) and not valid_header_proof(proof):
                raise ValueError("Unproved original header column contract")
            for observation in proof.get("observations", []):
                for column in observation.get("columns", []):
                    physical = "physical_header_lines" in column or any(
                        isinstance(part, dict)
                        and part.get("method") == "physical_header_line"
                        for part in column.get("parts", [])
                    )
                    if physical and (
                        not physical_header_valid(column)
                        or detector_header_conflict(
                            column.get("detection_parts", []),
                            column.get("raw_text", ""),
                        )
                        or column.get("detector_conflict") is not False
                        or column.get("crosses_boundary") is not False
                    ):
                        raise ValueError("Unproved original physical header lines")
    errors = []
    for row in payload.get("rows", []):
        sources = row.get("activity_sources", [])
        if not isinstance(sources, list):
            raise TypeError("Malformed original header evidence sources")
        for source in sources:
            if not isinstance(source, dict):
                raise TypeError("Malformed original header evidence source")
            reference = source.get("header_resolution")
            if reference is None:
                continue
            if not isinstance(reference, dict) or not isinstance(
                reference.get("evidence_ref"), str
            ):
                raise TypeError("Missing original header evidence reference")
            key = reference["evidence_ref"]
            proof = catalog.get(key)
            if proof is None or reference != _reference(key, proof):
                raise ValueError("Unproved original header evidence reference")
            if proof["status"] == "unresolved":
                errors.append(f"Original header requires review: {row.get('cpd', '')}.")
    return list(dict.fromkeys(errors))
