"""Optional serial evidence sidecar over the existing HTTP/cache client.

The parent owns one budget instance per job and passes the same instance to all
consumers. This module selects supplied hypotheses only; it cannot mutate source,
chemistry, stage state or formal acceptance, and never invokes itself in a loop.
"""

from __future__ import annotations

import fcntl
import json
import os
import sqlite3
import stat
import threading
from pathlib import Path
from typing import Protocol

from .client import llm_chat
from .config import (
    EvidenceResolutionConfig,
    get_evidence_resolution_config,
    snapshot_disclosure_allowed,
)
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
from .http_transport import Cancellation
from .private_state import read_budget, write_private

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

    def __init__(
        self, job_id: str, max_calls: int = 8, *, ledger: Path | None = None
    ) -> None:
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
        self.ledger = ledger
        self._lock_fd: int | None = None

    @property
    def calls(self) -> int:
        if self.ledger is None:
            return self._calls
        return read_budget(self.ledger, self.job_id, self.max_calls)

    def acquire(self) -> bool:
        if not self._serial.acquire(blocking=False):
            return False
        if self.ledger is not None:
            try:
                fd = os.open(
                    str(self.ledger) + ".lock",
                    os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,
                    0o600,
                )
                self._lock_fd = fd
                info = os.fstat(fd)
                if (
                    not stat.S_ISREG(info.st_mode)
                    or info.st_uid != os.getuid()
                    or info.st_mode & 0o077
                ):
                    raise ValueError("Unsafe API budget lock")
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                self.release()
                return False
            except BaseException:
                self.release()
                raise
        return True

    def release(self) -> None:
        if self._lock_fd is not None:
            os.close(self._lock_fd)
            self._lock_fd = None
        self._serial.release()

    def reserve(self, limit: int) -> bool:
        used = self.calls
        if used >= min(self.max_calls, limit, 8):
            return False
        if self.ledger is not None:
            write_private(
                self.ledger,
                {"job_id": self.job_id, "limit": self.max_calls, "calls": used + 1},
            )
        self._calls = used + 1
        return True


class EvidenceResolver(Protocol):
    def __call__(
        self,
        request: EvidenceRequest,
        budget: EvidenceCallBudget,
        *,
        config: EvidenceResolutionConfig | None = None,
        cancel: Cancellation | None = None,
    ) -> EvidenceResolution: ...


def resolve_evidence(
    request: EvidenceRequest,
    budget: EvidenceCallBudget,
    *,
    config: EvidenceResolutionConfig | None = None,
    cancel: Cancellation | None = None,
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
    if not snapshot_disclosure_allowed(policy):
        return result("disabled", "authorization_revoked")
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
    if not budget.acquire():
        return result("unavailable", "serial_busy")
    denied = False

    def reserve_attempt() -> bool:
        nonlocal denied
        if not snapshot_disclosure_allowed(policy) or not budget.reserve(
            policy.max_calls
        ):
            denied = True
            return False
        return True

    try:
        content = llm_chat(
            messages,
            model=policy.model,
            max_tokens=policy.max_tokens,
            config={
                key: getattr(policy, key)
                for key in (
                    "endpoint",
                    "api_key",
                    "model",
                    "cache_path",
                    "protocol",
                    "response_mode",
                )
            },
            timeout=policy.timeout,
            max_retries=policy.retries,
            response_format=schema,
            max_response_chars=policy.max_output_chars,
            before_request=reserve_attempt,
            cancel=cancel,
            max_request_chars=policy.max_input_chars,
        )
        if denied:
            if not snapshot_disclosure_allowed(policy):
                return result("disabled", "authorization_revoked")
            return result("budget_exhausted", "call_budget")
        if not snapshot_disclosure_allowed(policy):
            return result("disabled", "authorization_revoked")
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
        budget.release()
