"""
LLM Client — 统一大模型调用客户端

对接 OpenAI 兼容协议 LLM，支持：
- 文本理解、QA 校验
- 有界串行 HTTPS API
- 私有结果缓存（SQLite）；没有本地模型或第二条 HTTP 链路
"""

import json
import logging
import time
from collections.abc import Callable

import requests

from .config import get_llm_config
from .external_api import validate_external_endpoint
from .http_transport import Cancellation, HttpCarrierError, bounded_post
from .protocol_adapters import build_request, response_text
from .response_cache import _cache_key, _cache_set, _cached

logger = logging.getLogger(__name__)

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
) -> str:
    """调用 LLM，返回文本响应。"""
    llm_cfg = get_llm_config() if config is None else config
    model = model or str(llm_cfg.get("model", ""))
    endpoint = str(llm_cfg.get("endpoint", "")).rstrip("/")
    api_key = str(llm_cfg.get("api_key", "")).strip()
    timeout = timeout if timeout is not None else int(llm_cfg.get("timeout", 30) or 30)
    if cancel is not None and cancel.is_set():
        return ""
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
    ):
        raise ValueError("Invalid LLM request bounds")
    deadline = time.monotonic() + timeout
    cache_path = str(llm_cfg.get("cache_path", "") or "")
    use_cache = cache and temperature == 0.0

    if not api_key:
        logger.error("LLM_API_KEY is not set; skipping LLM request")
        return ""
    if not endpoint:
        logger.error("LLM endpoint is not set; skipping LLM request")
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
    )
    if use_cache:
        cached = _cached(
            key,
            cache_ttl,
            cache_path=cache_path,
            max_response_chars=max_response_chars,
        )
        if cached is not None:
            return cached

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

    attempts = max_retries + 1
    for attempt in range(attempts):
        remaining = deadline - time.monotonic()
        if (
            remaining <= 0
            or (cancel is not None and cancel.is_set())
            or (before_request is not None and not before_request())
        ):
            return ""
        try:
            try:
                resp = bounded_post(
                    wire.url,
                    headers=wire.headers,
                    json=wire.payload,
                    timeout=remaining,
                    deadline=deadline,
                    max_body_bytes=max_response_chars * 6 + 8192,
                    cancel=cancel,
                    require_public=True,
                )
                content = _response_text(
                    resp, max_response_chars, deadline, wire.protocol
                )
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                logger.error("LLM response parse failed (%s)", type(exc).__name__)
                break

            if use_cache:
                _cache_set(key, content, cache_path=cache_path)

            return content
        except HttpCarrierError:
            logger.warning("Owned HTTP carrier failed or was cancelled; no retry")
            return ""
        except requests.exceptions.Timeout:
            logger.warning("LLM timeout (attempt %s/%s)", attempt + 1, attempts)
        except requests.exceptions.RequestException as exc:
            logger.warning(
                "LLM request failed (%s, attempt %s/%s)",
                type(exc).__name__,
                attempt + 1,
                attempts,
            )

    return ""
