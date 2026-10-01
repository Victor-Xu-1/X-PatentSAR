"""Read-only identity/QA authority checks; no competing QA implementation."""

from __future__ import annotations

import re
from typing import Any

from patent_sar_extractor import contracts as core

from .models import STAGES, Acceptance

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


def _failure_messages(payloads: dict[str, Any], marker: object) -> list[str] | None:
    summary = payloads.get("summary") or {}
    steps = summary.get("steps", {})
    failed_steps = (
        [
            steps[name]
            for name in STAGES
            if isinstance(steps.get(name), dict)
            and steps[name].get("status") == "failed"
        ]
        if isinstance(steps, dict)
        else []
    )
    status = summary.get("status")
    marker_stage = marker.get("stage") if isinstance(marker, dict) else None
    resolved_stage = (
        {"final_export": "final", "final_qa": "qa"}.get(marker_stage, marker_stage)
        if isinstance(marker_stage, str)
        else None
    )
    if (
        status in ("running", "qa_pending")
        and not failed_steps
        and isinstance(steps, dict)
        and isinstance(steps.get(resolved_stage), dict)
        and steps[resolved_stage].get("status") == "ok"
        and core.artifact_identity_matches(
            marker, core.FAILURE_MARKER_SCHEMA, core.FAILURE_MARKER_SCHEMA_VERSION
        )
    ):
        # Core retains the old marker until final QA clears it. A successfully
        # rerun stage supersedes its old message for the provisional live view,
        # never for completed/formally accepted output.
        marker = None
    if (
        marker is None
        and not failed_steps
        and not (isinstance(status, str) and status.startswith("failed"))
    ):
        return None
    collections = [marker.get("errors", [])] if isinstance(marker, dict) else []
    collections.extend(step.get("acceptance_errors", []) for step in failed_steps)
    messages: list[str] = []
    for entries in collections:
        if not isinstance(entries, list):
            messages.append("Core failure error collection is invalid.")
            continue
        for entry in entries[:100]:
            message = public_error_text(entry)
            if message not in messages:
                messages.append(message)
            if len(messages) >= 100:
                return messages
    return messages or [
        "The current extraction stopped before formal acceptance; inspect the private run logs."
    ]


def authority(
    payloads: dict[str, Any], *, pdf_verified: bool, marker: object
) -> tuple[Acceptance, bool]:
    present = [name for name in ARTIFACTS if payloads.get(name) is not None]
    if not present:
        if marker is not None:
            return Acceptance(
                state="failed", errors=_failure_messages({}, marker) or []
            ), False
        return Acceptance(state="not_run"), False
    # Missing downstream artifacts are normal at checkpoints and strict early
    # stops. Historical identity is determined only by evidence that is present.
    if not all(current(payloads[name], name) for name in present):
        return Acceptance(
            state="historical",
            errors=[
                "Run artifacts have absent or non-current identities; historical review only."
            ],
        ), True
    failure_messages = _failure_messages(payloads, marker)
    if failure_messages is not None:
        return Acceptance(state="failed", errors=failure_messages), False
    if not pdf_verified:
        return Acceptance(
            state="failed",
            errors=[
                "The original PDF has not been verified against this run's fingerprint."
            ],
        ), False
    missing = [name for name in ARTIFACTS if payloads.get(name) is None]
    if missing:
        summary = payloads.get("summary") or {}
        finished = (
            summary.get("status") == "complete"
            or summary.get("status") == "review"
            or payloads.get("qa") is not None
        )
        return Acceptance(
            state="failed" if finished else "not_run",
            errors=[
                "Current extraction is incomplete; missing artifact evidence: "
                + ", ".join(missing)
                + "."
            ],
        ), False
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
    if not modes or not complete_shapes:
        return Acceptance(
            state="failed",
            errors=[
                "Current artifact shapes or production execution modes do not satisfy formal acceptance."
            ],
        ), False
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
        if payloads["summary"].get("status") != "complete":
            return Acceptance(
                state="not_run",
                errors=[
                    "The current run has not recorded completed formal extraction."
                ],
            ), False
        return Acceptance(state="accepted"), False
    messages = [public_error_text(e) for e in errors[:100]]
    if not messages:
        messages = [
            "Deterministic QA did not accept this run or a strict failure marker remains."
        ]
    return Acceptance(state="failed", errors=messages), False
