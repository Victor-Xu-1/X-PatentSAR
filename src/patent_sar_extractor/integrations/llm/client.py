"""
LLM Client — 统一大模型调用客户端

对接 OpenAI 兼容协议 LLM，支持：
- 文本理解、QA 校验
- 有界串行 HTTPS API
- 私有结果缓存（SQLite）；没有本地模型或第二条 HTTP 链路
"""

import json
import logging
import sqlite3
import time
from collections.abc import Callable
from functools import partial

import requests

from .api_failures import APIProblem, APIRequestError
from .config import get_llm_config
from .external_api import validate_external_endpoint
from .http_transport import (
    POLL_SECONDS,
    Cancellation,
    DispatchGuard,
    HttpCancelled,
    HttpCarrierError,
    bounded_post,
)
from .protocol_adapters import build_request, response_text
from .response_cache import (
    _cache_discard,
    _cache_key,
    _cache_set,
    _cached,
    is_cache_unavailable,
)

logger = logging.getLogger(__name__)
FailureHook = Callable[[APIProblem], None]
ContentValidator = Callable[[str], None]
_CONTENT_ERRORS = (KeyError, IndexError, TypeError, ValueError, RecursionError)

# ── 核心调用 ──


def _response_text(
    response: bytes, limit: int, deadline: float, protocol: str = "openai-compatible"
) -> str:
    # Bound bytes before decoding the envelope, not just its message text.
    maximum = limit * 6 + 8192
    if (
        not isinstance(response, bytes)
        or len(response) > maximum
        or time.monotonic() >= deadline
    ):
        raise ValueError("LLM response exceeded its resource bound")
    result = json.loads(response)
    raw = response_text(result, protocol)
    if not isinstance(raw, str) or len(raw) > limit:
        raise ValueError("LLM response content is invalid or excessive")
    return raw.strip()


def _report(problem: APIProblem, on_failure: FailureHook | None) -> None:
    logger.warning(
        "LLM API failure: %s (status=%s)", problem.reason, problem.http_status
    )
    if on_failure is not None:
        on_failure(problem)


def _stopped(
    deadline: float, cancel: Cancellation | None, on_failure: FailureHook | None
) -> bool:
    reason = None
    if cancel is not None and cancel.is_set():
        reason = "cancelled"
    elif time.monotonic() >= deadline:
        reason = "deadline_exceeded"
    if reason is not None:
        _report(APIProblem(reason), on_failure)
    return reason is not None


def _optional_cache(
    operation: Callable[[], str | None], on_failure: FailureHook | None
) -> str | None:
    try:
        return operation()
    except (sqlite3.Error, OSError) as exc:
        if not is_cache_unavailable(exc):
            raise
    _report(APIProblem("cache_unavailable"), on_failure)
    return None


def _valid_content(
    content: str,
    limit: int,
    validator: ContentValidator | None,
    reason: str,
    on_failure: FailureHook | None,
) -> bool:
    try:
        if not isinstance(content, str) or len(content) > limit:
            raise ValueError("Invalid or excessive API content")
        if validator is not None:
            validator(content)
    except _CONTENT_ERRORS:
        _report(APIProblem(reason), on_failure)
        return False
    return True


def _retry_ready(
    problem: APIProblem,
    deadline: float,
    cancel: Cancellation | None,
    on_failure: FailureHook | None,
) -> bool:
    if not problem.retryable or _stopped(deadline, cancel, on_failure):
        return False
    delay = (
        problem.retry_after_seconds if problem.retry_after_seconds is not None else 0.1
    )
    remaining = deadline - time.monotonic()
    if delay >= remaining:
        return False  # No useful retry fits; do not wait or reserve another attempt.
    wake = time.monotonic() + delay
    while time.monotonic() < wake:
        if _stopped(deadline, cancel, on_failure):
            return False
        time.sleep(min(POLL_SECONDS, max(0.0, wake - time.monotonic())))
    return not _stopped(deadline, cancel, on_failure)


def llm_chat(
    messages: list,
    model: str | None = None,
    temperature: float = 0.0,
    max_tokens: int = 1024,
    cache: bool = True,
    cache_ttl: int = 24,
    *,
    config: dict | None = None,
    timeout: int | None = None,
    max_retries: int = 0,
    response_format: dict | None = None,
    max_response_chars: int = 8192,
    before_request: Callable[[], bool] | None = None,
    cancel: Cancellation | None = None,
    max_request_chars: int = 32768,
    validate_content: Callable[[str], None] | None = None,
    on_failure: Callable[[APIProblem], None] | None = None,
    validation_identity: str = "",
    dispatch_guard: DispatchGuard | None = None,
) -> str:
    """Return text only after local validation, including on every cache hit.

    Validation rejects with ValueError/TypeError/KeyError/IndexError/RecursionError;
    rejected fresh content is not cached or retried. A stable consumer/version
    validation_identity isolates old unvalidated observations. Failure hooks get
    safe metadata; hook/persistence bugs and unsafe cache access are not swallowed.
    """
    if cancel is not None and cancel.is_set():
        _report(APIProblem("cancelled"), on_failure)
        return ""
    llm_cfg = get_llm_config() if config is None else config
    model = model or str(llm_cfg.get("model", ""))
    endpoint = str(llm_cfg.get("endpoint", "")).rstrip("/")
    api_key = str(llm_cfg.get("api_key", "")).strip()
    timeout = timeout if timeout is not None else int(llm_cfg.get("timeout", 30) or 30)
    if (
        type(max_retries) is not int
        or not 0 <= max_retries <= 1
        or type(max_response_chars) is not int
        or not 1 <= max_response_chars <= 16384
        or type(timeout) is not int
        or not 1 <= timeout <= 45
        or type(max_tokens) is not int
        or not 1 <= max_tokens <= 2048
        or type(max_request_chars) is not int
        or not 1 <= max_request_chars <= 32768
        or (validate_content is not None and not callable(validate_content))
        or (on_failure is not None and not callable(on_failure))
    ):
        raise ValueError("Invalid LLM request bounds")
    deadline = time.monotonic() + timeout
    cache_path = str(llm_cfg.get("cache_path", "") or "")
    use_cache = cache and temperature == 0.0

    if not api_key:
        _report(APIProblem("configuration_unavailable"), on_failure)
        return ""
    if not endpoint:
        _report(APIProblem("configuration_unavailable"), on_failure)
        return ""

    endpoint = validate_external_endpoint(endpoint)

    key = _cache_key(
        messages,
        model,
        temperature,
        endpoint,
        max_tokens,
        response_format,
        max_response_chars,
        llm_cfg.get("protocol", "openai-compatible"),
        llm_cfg.get("response_mode", "json-schema"),
        validation_identity,
    )
    wire = build_request(
        {**llm_cfg, "endpoint": endpoint, "api_key": api_key},
        messages,
        model,
        temperature,
        max_tokens,
        response_format,
    )
    if (
        len(json.dumps(wire.payload, ensure_ascii=False, separators=(",", ":")))
        > max_request_chars
    ):
        raise ValueError("API request exceeded the evidence input budget")

    if use_cache:
        cached = _optional_cache(
            lambda: _cached(
                key,
                cache_ttl,
                cache_path=cache_path,
                max_response_chars=max_response_chars,
            ),
            on_failure,
        )
        if cached is not None:
            if _valid_content(
                cached,
                max_response_chars,
                validate_content,
                "invalid_cached_content",
                on_failure,
            ):
                return "" if _stopped(deadline, cancel, on_failure) else cached
            _optional_cache(
                partial(_cache_discard, key, cached, cache_path=cache_path), on_failure
            )

    attempts = max_retries + 1
    for attempt in range(attempts):
        if _stopped(deadline, cancel, on_failure):
            return ""
        if before_request is not None and not before_request():
            _report(APIProblem("budget_exhausted"), on_failure)
            return ""
        # Durable reservation can take time or revoke consent/cancel concurrently.
        if _stopped(deadline, cancel, on_failure):
            return ""
        try:
            try:
                resp = bounded_post(
                    wire.url,
                    headers=wire.headers,
                    json=wire.payload,
                    timeout=deadline - time.monotonic(),
                    deadline=deadline,
                    max_body_bytes=max_response_chars * 6 + 8192,
                    cancel=cancel,
                    require_public=True,
                    dispatch_guard=dispatch_guard,
                )
                content = _response_text(
                    resp, max_response_chars, deadline, wire.protocol
                )
            except _CONTENT_ERRORS:
                if not _stopped(deadline, cancel, on_failure):
                    _report(APIProblem("invalid_response"), on_failure)
                return ""
        except APIRequestError as exc:
            problem = exc.problem
        except HttpCancelled:
            _report(APIProblem("cancelled"), on_failure)
            return ""
        except HttpCarrierError:
            _report(APIProblem("carrier_error"), on_failure)
            return ""
        except requests.exceptions.Timeout:
            problem = APIProblem("timeout", retryable=True)
        except requests.exceptions.RequestException:
            problem = APIProblem("request_error")
        else:
            if not _valid_content(
                content,
                max_response_chars,
                validate_content,
                "invalid_content",
                on_failure,
            ):
                return ""
            if _stopped(deadline, cancel, on_failure):
                return ""
            if use_cache:
                _optional_cache(
                    partial(_cache_set, key, content, cache_path=cache_path),
                    on_failure,
                )
            return "" if _stopped(deadline, cancel, on_failure) else content
        _report(problem, on_failure)
        if attempt + 1 >= attempts or not _retry_ready(
            problem, deadline, cancel, on_failure
        ):
            return ""
    return ""
