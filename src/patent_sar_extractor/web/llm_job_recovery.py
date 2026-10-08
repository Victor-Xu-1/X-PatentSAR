"""Read-only job API health and explicit credential renewal on an idle attempt."""

from __future__ import annotations

import re
from pathlib import Path

from patent_sar_extractor.integrations.llm.config import snapshot_disclosure_allowed
from patent_sar_extractor.integrations.llm.credential_authorization import (
    current_credential,
)
from patent_sar_extractor.integrations.llm.job_context import read_context
from patent_sar_extractor.integrations.llm.job_health import (
    BLOCKED_REASONS,
    gate,
    read_state,
)
from patent_sar_extractor.integrations.llm.private_state import read_budget

from .errors import WebError
from .llm_models import LLMRecovery


def job_context(store, row: dict, spec: dict):
    identifier = spec.get("llm_context_id")
    if not identifier:
        return None
    if not isinstance(identifier, str) or not re.fullmatch(r"[a-f0-9]{32}", identifier):
        raise ValueError("Malformed job API context")
    with store.connect() as connection:
        owner = connection.execute(
            "SELECT project_id FROM jobs WHERE id=?", (identifier,)
        ).fetchone()
    if owner is None or owner["project_id"] != row["project_id"]:
        raise ValueError("Foreign job API context")
    context = read_context(Path(store.root) / "llm" / f"{identifier}.policy.json")
    if context.original_sha256 != spec.get("sha256"):
        raise ValueError("Foreign original in job API context")
    return context


def recovery_view(store, row: dict, spec: dict, resumable: bool) -> LLMRecovery | None:
    try:
        context = job_context(store, row, spec)
        if context is None:
            return None
        policy = context.policy
        used = read_budget(context.ledger, context.job_id, policy.max_calls)
        remaining = policy.max_calls - used
        if policy.mode == "off" or not policy.data_consent:
            return LLMRecovery(
                status="disabled",
                reason="off",
                remaining_calls=remaining,
                can_reauthorize=False,
            )
        authorized = snapshot_disclosure_allowed(policy)
        blocked = gate(
            context.ledger,
            context.job_id,
            attempt_id=row["id"] if row["status"] == "running" else "",
        )
        reason = (
            blocked[0]
            if blocked and blocked[0] in BLOCKED_REASONS - {"authentication_failed"}
            else "authorization_revoked"
            if not authorized
            else blocked[0]
            if blocked
            else None
        )
        if remaining == 0:
            return LLMRecovery(
                status="exhausted",
                reason="call_budget",
                remaining_calls=0,
                can_reauthorize=False,
            )
        can_renew = bool(
            resumable
            and policy.authorization_file
            and current_credential(policy)
            and reason in {"authorization_revoked", "authentication_failed"}
        )
        if reason:
            delay = blocked[1] if blocked and authorized else None
            return LLMRecovery(
                status="cooldown" if delay is not None else "blocked",
                reason=reason,
                remaining_calls=remaining,
                retry_after_seconds=delay,
                can_reauthorize=can_renew,
            )
        health = read_state(context.ledger, context.job_id)
        last = health["reason"] if health else None
        return LLMRecovery(
            status="unavailable"
            if last
            in {
                "invalid_response",
                "invalid_evidence_selection",
                "cancelled",
                "rate_limited",
                "provider_unavailable",
                "timeout",
                "transport_unavailable",
            }
            else "ready",
            reason=last
            if last not in {"authorization_updated", "response_validated"}
            else None,
            remaining_calls=remaining,
            can_reauthorize=False,
        )
    except (OSError, ValueError, TypeError, WebError):
        return LLMRecovery(
            status="unavailable",
            reason="control_unavailable",
            remaining_calls=None,
            can_reauthorize=False,
        )


def renew_job_authorization(service, llm_settings, job_id: str, body):
    from .attempts import spec_record
    from .history_storage import ensure_job_visible, ensure_project_visible

    current = service.job(job_id)
    if (
        not current.can_resume
        or not current.llm_recovery
        or not current.llm_recovery.can_reauthorize
    ):
        raise WebError(
            409,
            "llm_renewal_unavailable",
            "This idle task cannot renew its API authorization.",
        )
    with service.store.connect(write=True) as connection:
        ensure_job_visible(connection, job_id)
        row = dict(
            connection.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        )
        ensure_project_visible(connection, row["project_id"])
        if (
            row["status"] not in {"failed", "interrupted", "cancelled"}
            or row["identity"]
            or connection.execute(
                "SELECT 1 FROM jobs WHERE project_id=? AND status IN ('queued','running')",
                (row["project_id"],),
            ).fetchone()
        ):
            raise WebError(
                409,
                "job_active",
                "No authorization was changed while a task is active.",
            )
        context = job_context(service.store, row, spec_record(row["spec"]))
        if context is None:
            raise WebError(
                409, "llm_renewal_unavailable", "The task has no API policy to renew."
            )
        llm_settings.renew_job(context, body.expected_revision)
    return service.job(job_id)
