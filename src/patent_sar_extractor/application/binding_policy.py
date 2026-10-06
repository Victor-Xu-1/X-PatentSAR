"""Source-catalog binding policy: no activity filter or parent-ID relabelling."""

from __future__ import annotations

import json
from pathlib import Path

from patent_sar_extractor.artifact_io import load_json
from patent_sar_extractor.contracts import (
    BINDINGS_SCHEMA,
    BINDINGS_SCHEMA_VERSION,
    artifact_identity_matches,
)
from patent_sar_extractor.core.formal_structure import (
    confirmed_binding,
    coverage_errors,
    image_exists,
)

from .stage_cache import _fingerprint_matches

WORKING_ROOT = Path.cwd()


def _load_bindings_from_json(path: str) -> tuple[dict, list[dict]]:
    with open(path, encoding="utf-8") as source:
        payload = json.load(source)
    if not isinstance(payload, dict) or not isinstance(
        payload.get("final_bindings"), list
    ):
        raise ValueError("Malformed formal binding artifact")  # noqa: TRY004 -- shared schema boundary
    return payload, payload["final_bindings"]


def _binding_acceptance_errors(
    bindings_payload: dict, locator: dict | None = None
) -> list[str]:
    """Recheck the entire proved catalog; activity membership is irrelevant."""
    del locator
    if not artifact_identity_matches(
        bindings_payload, BINDINGS_SCHEMA, BINDINGS_SCHEMA_VERSION
    ):
        raise ValueError("Binding producer returned an incompatible artifact")
    errors = coverage_errors(bindings_payload)
    bindings = bindings_payload["final_bindings"]
    missing = [
        row.get("cpd") for row in bindings if not image_exists(row, str(WORKING_ROOT))
    ]
    if missing:
        raise FileNotFoundError(
            f"Confirmed structure image files are missing ({missing[:10]})."
        )
    if any(not confirmed_binding(row) for row in bindings):
        errors.append("One or more bindings lack strong confirmatory evidence.")
    return errors


def _load_reusable_bindings(
    bind_json: str, fingerprint: dict, locator: dict | None = None
) -> dict | None:
    if not _fingerprint_matches(bind_json, fingerprint):
        return None
    payload = load_json(bind_json, {})
    if not artifact_identity_matches(payload, BINDINGS_SCHEMA, BINDINGS_SCHEMA_VERSION):
        return None
    # No write/retag/filter of historical or partial bindings during reuse.
    if _binding_acceptance_errors(payload, locator):
        return None
    return payload


def _standalone_smiles_binding_preflight_errors(bindings_payload: dict) -> list[str]:
    if not isinstance(bindings_payload, dict):
        return ["SMILES input must be a current source-led binding artifact."]
    if not artifact_identity_matches(
        bindings_payload, BINDINGS_SCHEMA, BINDINGS_SCHEMA_VERSION
    ):
        return ["SMILES input does not match the current binding schema and ruleset."]
    return _binding_acceptance_errors(bindings_payload)
