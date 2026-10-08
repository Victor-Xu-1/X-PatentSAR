"""Persistent bounded API fault state shared by all consumers of one job budget."""

from __future__ import annotations

import math
import os
import re
import time
from pathlib import Path

from .api_failures import APIProblem
from .private_state import read_private, write_private

SCHEMA = {"name": "patentsar.api-job-health", "version": 2}
BLOCKED_REASONS = {
    "authentication_failed",
    "unsafe_cache",
    "carrier_error",
    "configuration_unavailable",
    "redirect_rejected",
    "http_error",
}
REASONS = BLOCKED_REASONS | {
    "rate_limited",
    "provider_unavailable",
    "timeout",
    "transport_unavailable",
    "invalid_response",
    "invalid_evidence_selection",
    "cancelled",
    "cache_unavailable",
    "authorization_updated",
    "response_validated",
}


def state_path(ledger: Path) -> Path:
    return ledger.with_name(
        ledger.name.removesuffix(".budget.json") + ".api-state.json"
    )


def read_state(ledger: Path, job_id: str) -> dict | None:
    path = state_path(ledger)
    if not path.exists() and not path.is_symlink():
        return None
    value = read_private(path)
    if (
        set(value)
        != {
            "schema",
            "job_id",
            "reason",
            "http_status",
            "retryable",
            "retry_at",
            "attempt_id",
        }
        or value["schema"] != SCHEMA
        or value["job_id"] != job_id
        or value["reason"] not in REASONS
        or type(value["retryable"]) is not bool
        or value["http_status"] is not None
        and (
            type(value["http_status"]) is not int
            or not 300 <= value["http_status"] <= 599
        )
        or type(value["retry_at"]) not in (float, int)
        or not math.isfinite(value["retry_at"])
        or not 0 <= value["retry_at"] <= 1e12
        or not isinstance(value["attempt_id"], str)
        or value["attempt_id"]
        and not re.fullmatch(r"[a-f0-9]{32}", value["attempt_id"])
    ):
        raise ValueError("Malformed API job health evidence")
    return value


def gate(
    ledger: Path | None, job_id: str, *, attempt_id: str | None = None
) -> tuple[str, float | None] | None:
    if ledger is None:
        return None
    value = read_state(ledger, job_id)
    if value is None:
        return None
    if value["reason"] in BLOCKED_REASONS:
        return value["reason"], None
    remaining = value["retry_at"] - time.time()
    current = (
        os.environ.get("PATENTSAR_API_ATTEMPT_ID", "")
        if attempt_id is None
        else attempt_id
    )
    if (
        current
        and current == value["attempt_id"]
        and value["reason"]
        in {"rate_limited", "provider_unavailable", "timeout", "transport_unavailable"}
    ):
        return value["reason"], min(45.0, max(0.0, remaining))
    if remaining > 0:
        return value["reason"], min(45.0, remaining)
    return None


def record_fault(ledger: Path | None, job_id: str, problem: APIProblem) -> None:
    if ledger is None:
        return
    if problem.reason not in REASONS:
        raise ValueError("Unknown API failure reason")
    delay = problem.retry_after_seconds
    if delay is not None and (
        type(delay) not in (int, float)
        or not math.isfinite(delay)
        or not 0 <= delay <= 45
    ):
        raise ValueError("Invalid bounded API retry delay")
    # A single failure cannot burn the whole task cap on subsequent tables.
    # Recovery is explicit; this is a circuit gate, never a sleep/retry loop.
    cooldown = (
        min(45.0, delay if delay is not None else 30.0)
        if problem.retryable or problem.reason == "transport_unavailable"
        else 0.0
    )
    write_private(
        state_path(ledger),
        {
            "schema": SCHEMA,
            "job_id": job_id,
            "reason": problem.reason,
            "http_status": problem.http_status,
            "retryable": problem.retryable,
            "retry_at": time.time() + cooldown if cooldown else 0.0,
            "attempt_id": os.environ.get("PATENTSAR_API_ATTEMPT_ID", ""),
        },
    )


def clear_state(
    ledger: Path, job_id: str, *, reason: str = "authorization_updated"
) -> None:
    """Keep the record as an explicit recovered state, not filesystem cleanup."""
    value = read_state(ledger, job_id)
    if value is None:
        return
    if reason not in {"authorization_updated", "response_validated"}:
        raise ValueError("Unknown API recovery event")
    write_private(
        state_path(ledger),
        {
            **value,
            "reason": reason,
            "http_status": None,
            "retryable": False,
            "retry_at": 0.0,
        },
    )
