"""Safe bounded API failure metadata, never provider bodies or credentials."""

from __future__ import annotations

import math
import re
import time
from dataclasses import asdict, dataclass
from email.utils import parsedate_to_datetime
from typing import Any

MAX_RETRY_AFTER_SECONDS = 45.0
_REASONS = frozenset(
    {
        "authentication_failed",
        "rate_limited",
        "server_error",
        "http_error",
        "redirect_rejected",
        "timeout",
        "request_error",
        "carrier_error",
        "cancelled",
        "deadline_exceeded",
        "budget_exhausted",
        "invalid_response",
        "invalid_content",
        "invalid_cached_content",
        "cache_unavailable",
        "configuration_unavailable",
    }
)


@dataclass(frozen=True, slots=True)
class APIProblem:
    reason: str
    http_status: int | None = None
    retryable: bool = False
    retry_after_seconds: float | None = None

    def __post_init__(self) -> None:
        delay = self.retry_after_seconds
        if (
            not isinstance(self.reason, str)
            or self.reason not in _REASONS
            or (
                self.http_status is not None
                and (
                    type(self.http_status) is not int
                    or not 100 <= self.http_status <= 599
                )
            )
            or type(self.retryable) is not bool
            or (
                delay is not None
                and (
                    type(delay) not in (int, float)
                    or not 0 <= delay <= MAX_RETRY_AFTER_SECONDS
                    or not math.isfinite(delay)
                )
            )
        ):
            raise ValueError("Invalid API failure metadata")
        if delay is not None:
            object.__setattr__(self, "retry_after_seconds", float(delay))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Any) -> APIProblem:
        if not isinstance(value, dict) or set(value) != {
            "reason",
            "http_status",
            "retryable",
            "retry_after_seconds",
        }:
            raise ValueError("Invalid API failure envelope")
        return cls(**value)


class APIRequestError(RuntimeError):
    """A failed request with safe machine metadata as its only error detail."""

    def __init__(self, problem: APIProblem):
        self.problem = problem
        super().__init__(problem.reason)


def parse_retry_after(value: str | None, *, now: float | None = None) -> float | None:
    """Accept a bounded delta/date; invalid, negative and nonfinite values drop."""
    if not isinstance(value, str) or len(value) > 128:
        return None
    value = value.strip()
    try:
        if re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", value):
            seconds = float(value)
        else:
            date = parsedate_to_datetime(value)
            if date.tzinfo is None:
                return None
            seconds = max(0.0, date.timestamp() - (time.time() if now is None else now))
    except (ValueError, TypeError, OverflowError):
        return None
    if not math.isfinite(seconds):
        return None
    return min(seconds, MAX_RETRY_AFTER_SECONDS)


def http_problem(status: int, retry_after: str | None = None) -> APIProblem:
    if status in {401, 403}:
        reason = "authentication_failed"
    elif status == 429:
        reason = "rate_limited"
    elif 500 <= status <= 599:
        reason = "server_error"
    elif 300 <= status <= 399:
        reason = "redirect_rejected"
    else:
        reason = "http_error"
    return APIProblem(
        reason,
        status,
        reason in {"rate_limited", "server_error"},
        parse_retry_after(retry_after),
    )
