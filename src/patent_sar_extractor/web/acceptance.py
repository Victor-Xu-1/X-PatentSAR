"""Read-only identity/QA authority checks; no competing QA implementation."""

from __future__ import annotations

import re
from typing import Any

from patent_sar_extractor import contracts as core

from .models import Acceptance

ARTIFACTS = {
    "summary": (
        "pipeline_summary.json",
        core.RUN_SUMMARY_SCHEMA,
        core.RUN_SUMMARY_SCHEMA_VERSION,
    ),
    "classification": (
        "page_classification/page_classification.json",
        core.PAGE_CLASSIFICATION_SCHEMA,
        core.PAGE_CLASSIFICATION_SCHEMA_VERSION,
    ),
    "activity": (
        "activity/activity_data.json",
        core.ACTIVITY_SCHEMA,
        core.ACTIVITY_SCHEMA_VERSION,
    ),
    "locator": (
        "structure_pages/locator.json",
        core.STRUCTURE_LOCATION_SCHEMA,
        core.STRUCTURE_LOCATION_SCHEMA_VERSION,
    ),
    "structures": (
        "structures/metadata.json",
        core.STRUCTURES_SCHEMA,
        core.STRUCTURES_SCHEMA_VERSION,
    ),
    "bindings": (
        "structure_bindings/bindings.json",
        core.BINDINGS_SCHEMA,
        core.BINDINGS_SCHEMA_VERSION,
    ),
    "smiles": (
        "smiles/smiles_results.json",
        core.SMILES_SCHEMA,
        core.SMILES_SCHEMA_VERSION,
    ),
    "qa": (
        "final_qa_report.json",
        core.QA_REPORT_SCHEMA,
        core.QA_REPORT_SCHEMA_VERSION,
    ),
}


def current(payload: object, name: str) -> bool:
    _, schema, version = ARTIFACTS[name]
    return core.artifact_identity_matches(payload, schema, version)


def public_error_text(value: object) -> str:
    if not isinstance(value, str):
        return "Core acceptance reported an invalid error entry."
    text = value[:500].replace("\n", " ").replace("\r", " ")
    text = re.sub(r"(?:[A-Za-z]:[\\/]|/)[^\s,;\"']+", "[path]", text)
    if "traceback" in text.lower():
        return "Core acceptance failed; inspect the private run logs."
    return text


def authority(
    payloads: dict[str, Any], *, pdf_verified: bool, marker: object
) -> tuple[Acceptance, bool]:
    present = [name for name, value in payloads.items() if value is not None]
    if not present:
        return Acceptance(state="not_run"), False
    identities = all(current(payloads.get(name), name) for name in ARTIFACTS)
    modes = (
        isinstance(payloads.get("bindings"), dict)
        and payloads["bindings"].get("execution_mode") == "production_activity_led"
        and isinstance(payloads.get("smiles"), dict)
        and payloads["smiles"].get("execution_mode") == "production_decimer"
    )
    complete_shapes = (
        isinstance(payloads.get("activity"), dict)
        and isinstance(payloads["activity"].get("active_cpds"), list)
        and isinstance(payloads["activity"].get("rows"), list)
        and bool(payloads["activity"].get("active_cpds"))
        and isinstance(payloads.get("bindings"), dict)
        and isinstance(payloads["bindings"].get("final_bindings"), list)
        and isinstance(payloads.get("smiles"), dict)
        and isinstance(payloads["smiles"].get("records"), list)
        and isinstance(payloads.get("structures"), dict)
        and isinstance(payloads["structures"].get("structures"), list)
        and isinstance(payloads.get("summary"), dict)
        and isinstance(payloads["summary"].get("steps"), dict)
    )
    if not identities or not modes or not complete_shapes or not pdf_verified:
        return Acceptance(
            state="historical",
            errors=[
                "Run identity, source PDF, or complete current artifact evidence is unavailable."
            ],
        ), True
    qa = payloads["qa"]
    decision = qa.get("acceptance")
    errors = decision.get("hard_errors", []) if isinstance(decision, dict) else []
    if not isinstance(errors, list):
        errors = ["Deterministic QA error collection is invalid."]
    if (
        qa.get("ok") is True
        and isinstance(decision, dict)
        and decision.get("ok") is True
        and not errors
        and marker is None
    ):
        return Acceptance(state="accepted"), False
    messages = [public_error_text(e) for e in errors[:100]]
    if not messages:
        messages = [
            "Deterministic QA did not accept this run or a strict failure marker remains."
        ]
    return Acceptance(state="failed", errors=messages), False
