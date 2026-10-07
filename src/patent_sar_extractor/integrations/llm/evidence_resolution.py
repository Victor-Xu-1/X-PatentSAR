"""Optional serial evidence sidecar over the existing HTTP/cache client.

The parent owns one budget instance per job and passes the same instance to all
consumers. This module selects supplied hypotheses only; it cannot mutate source,
chemistry, stage state or formal acceptance, and never invokes itself in a loop.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from typing import Protocol

from .client import llm_chat
from .config import EvidenceResolutionConfig, get_evidence_resolution_config
from .evidence_protocol import (
    IDENTIFIER,
    EvidenceCandidate,
    EvidenceObservation,
    EvidenceRequest,
    EvidenceResolution,
    ResolutionOutcome,
    ResolutionStatus,
    ResolvedCandidate,
    parse_candidates,
    request_messages,
    response_format,
    validate_request,
)

__all__ = [
    "EvidenceCallBudget",
    "EvidenceCandidate",
    "EvidenceObservation",
    "EvidenceRequest",
    "EvidenceResolution",
    "EvidenceResolver",
    "ResolutionOutcome",
    "ResolvedCandidate",
    "resolve_evidence",
]


class EvidenceCallBudget:
    """One shared per-job cap, counting every network attempt including retries."""

    def __init__(self, job_id: str, max_calls: int = 8) -> None:
        if (
            not IDENTIFIER.fullmatch(job_id)
            or type(max_calls) is not int
            or not 1 <= max_calls <= 8
        ):
            raise ValueError("Invalid per-job evidence budget")
        self.job_id = job_id
        self.max_calls = max_calls
        self._calls = 0
        self._serial = threading.Lock()

    @property
    def calls(self) -> int:
        return self._calls


class EvidenceResolver(Protocol):
    def __call__(
        self,
        request: EvidenceRequest,
        budget: EvidenceCallBudget,
        *,
        config: EvidenceResolutionConfig | None = None,
    ) -> EvidenceResolution: ...


def resolve_evidence(
    request: EvidenceRequest,
    budget: EvidenceCallBudget,
    *,
    config: EvidenceResolutionConfig | None = None,
) -> EvidenceResolution:
    """Return validated candidate references, or an explicit nonactionable state."""

    def result(
        status: ResolutionStatus,
        reason: str,
        candidates: tuple[ResolvedCandidate, ...] = (),
    ) -> EvidenceResolution:
        return EvidenceResolution(status, reason, candidates, budget.calls)

    try:
        policy = get_evidence_resolution_config() if config is None else config
        policy.validate()
    except (ValueError, TypeError, OSError, AttributeError):
        return result("unavailable", "invalid_configuration")
    if policy.mode == "off":
        return result("disabled", "off")
    if not policy.data_consent:
        return result("disabled", "data_consent_required")
    try:
        validate_request(request, budget.job_id)
    except (ValueError, TypeError, AttributeError):
        return result("unavailable", "invalid_request")
    if request.fault_kind != "evidence":
        return result("unavailable", "non_evidence_fault")
    if policy.mode == "on-error" and request.trigger != "on-error":
        return result("disabled", "trigger_not_enabled")
    messages, schema = request_messages(request), response_format(request)
    payload = {
        "messages": messages,
        "response_format": schema,
        "model": policy.model,
        "temperature": 0.0,
        "max_tokens": policy.max_tokens,
    }
    if (
        len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        > policy.max_input_chars
    ):
        return result("unavailable", "input_budget")
    if not budget._serial.acquire(blocking=False):
        return result("unavailable", "serial_busy")
    denied = False

    def reserve_attempt() -> bool:
        nonlocal denied
        if budget.calls >= min(budget.max_calls, policy.max_calls, 8):
            denied = True
            return False
        budget._calls += 1
        return True

    try:
        content = llm_chat(
            messages,
            model=policy.model,
            max_tokens=policy.max_tokens,
            config={
                key: getattr(policy, key)
                for key in ("endpoint", "api_key", "model", "cache_path")
            },
            timeout=policy.timeout,
            max_retries=policy.retries,
            response_format=schema,
            max_response_chars=policy.max_output_chars,
            before_request=reserve_attempt,
        )
        if denied:
            return result("budget_exhausted", "call_budget")
        if not content:
            return result("unavailable", "transport_unavailable")
        try:
            candidates = parse_candidates(content, request)
        except (ValueError, TypeError, RecursionError):
            return result("invalid_response", "invalid_evidence_selection")
        return result("resolved", "supplied_candidates_only", candidates)
    except (OSError, sqlite3.Error, ValueError, TypeError, RecursionError, MemoryError):
        return result("unavailable", "transport_unavailable")
    finally:
        budget._serial.release()
