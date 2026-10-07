"""
LLM Client — 统一大模型调用客户端

对接 OpenAI 兼容协议 LLM，支持：
- 文本理解、QA 校验
- 线程池并发
- 结果缓存（SQLite）
"""

import hashlib
import json
import logging
import os
import re
import sqlite3
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from .config import get_llm_config
from .http_transport import Cancellation, HttpCarrierError, bounded_post

logger = logging.getLogger(__name__)

# ── 缓存 ──


def _get_cache_db(cache_path: str | None = None):
    if cache_path is None:
        cache_path = str(get_llm_config().get("cache_path", "") or "")
    if not cache_path:
        return None
    os.makedirs(os.path.dirname(cache_path) or ".", exist_ok=True)
    db = sqlite3.connect(cache_path, timeout=10)
    db.execute(
        "CREATE TABLE IF NOT EXISTS llm_cache "
        "(cache_key TEXT PRIMARY KEY, response TEXT, created_at REAL)"
    )
    db.commit()
    return db


def _cache_key(
    messages: list,
    model: str,
    temperature: float,
    endpoint: str = "",
    max_tokens: int = 4096,
    response_format: dict | None = None,
    max_response_chars: int | None = None,
) -> str:
    identity = {
        "messages": messages,
        "model": model,
        "temperature": temperature,
        "endpoint": endpoint,
        "max_tokens": max_tokens,
    }
    if response_format is not None or max_response_chars is not None:
        identity.update(
            response_format=response_format, max_response_chars=max_response_chars
        )
    raw = json.dumps(
        identity,
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _cached(
    key: str,
    ttl_hours: int = 24,
    *,
    cache_path: str | None = None,
    max_response_chars: int | None = None,
) -> str | None:
    db = _get_cache_db(cache_path)
    if db is None:
        return None
    try:
        row = db.execute(
            "SELECT response FROM llm_cache WHERE cache_key=? AND created_at>? "
            "AND (? IS NULL OR length(response)<=?)",
            (
                key,
                time.time() - ttl_hours * 3600,
                max_response_chars,
                max_response_chars,
            ),
        ).fetchone()
        return row[0] if row else None
    finally:
        db.close()


def _cache_set(key: str, response: str, *, cache_path: str | None = None) -> None:
    db = _get_cache_db(cache_path)
    if db is None:
        return
    try:
        db.execute(
            "INSERT OR REPLACE INTO llm_cache VALUES (?, ?, ?)",
            (key, response, time.time()),
        )
        db.commit()
    finally:
        db.close()


# ── 核心调用 ──


def _response_text(response, limit: int | None, deadline: float | None) -> str:
    if limit is None:
        result = response.json()
    else:
        # Bound bytes before decoding a provider envelope, not just its eventual
        # message text. Six bytes cover a JSON-escaped Unicode character.
        maximum = limit * 6 + 8192
        if (
            not isinstance(response, bytes)
            or len(response) > maximum
            or (deadline is not None and time.monotonic() >= deadline)
        ):
            raise ValueError("LLM response exceeded its resource bound")
        result = json.loads(response)
        if result["choices"][0].get("finish_reason") != "stop":
            raise ValueError("LLM structured response was not complete")
    raw = result["choices"][0]["message"]["content"]
    if not isinstance(raw, str) or (limit is not None and len(raw) > limit):
        raise ValueError("LLM response content is invalid or excessive")
    return raw.strip()


def llm_chat(
    messages: list,
    model: str | None = None,
    temperature: float = 0.0,
    max_tokens: int = 4096,
    cache: bool = True,
    cache_ttl: int = 24,
    *,
    config: dict | None = None,
    timeout: int | None = None,
    max_retries: int = 2,
    response_format: dict | None = None,
    max_response_chars: int | None = None,
    before_request: Callable[[], bool] | None = None,
    cancel: Cancellation | None = None,
) -> str:
    """调用 LLM，返回文本响应。"""
    llm_cfg = get_llm_config() if config is None else config
    model = model or str(llm_cfg.get("model", ""))
    endpoint = str(llm_cfg.get("endpoint", "")).rstrip("/")
    api_key = str(llm_cfg.get("api_key", "")).strip()
    timeout = (
        timeout if timeout is not None else int(llm_cfg.get("timeout", 180) or 180)
    )
    bounded = max_response_chars is not None
    if bounded and cancel is not None and cancel.is_set():
        return ""
    if (
        type(max_retries) is not int
        or not 0 <= max_retries <= (1 if bounded else 2)
        or (
            bounded
            and (
                type(max_response_chars) is not int
                or not 1 <= max_response_chars <= 16384
                or not 1 <= timeout <= 45
            )
        )
    ):
        raise ValueError("Invalid LLM request bounds")
    deadline = time.monotonic() + timeout if bounded else None
    cache_path = str(llm_cfg.get("cache_path", "") or "")
    use_cache = cache and temperature == 0.0

    if not api_key:
        logger.error("LLM_API_KEY is not set; skipping LLM request")
        return ""
    if not endpoint:
        logger.error("LLM endpoint is not set; skipping LLM request")
        return ""

    key = _cache_key(
        messages,
        model,
        temperature,
        endpoint,
        max_tokens,
        response_format,
        max_response_chars,
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

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if response_format is not None:
        payload["response_format"] = response_format

    attempts = max_retries + 1
    for attempt in range(attempts):
        remaining = timeout if deadline is None else deadline - time.monotonic()
        if (
            remaining <= 0
            or (bounded and cancel is not None and cancel.is_set())
            or (before_request is not None and not before_request())
        ):
            return ""
        try:
            try:
                if bounded:
                    assert deadline is not None and max_response_chars is not None
                    resp = bounded_post(
                        f"{endpoint}/chat/completions",
                        headers=headers,
                        json=payload,
                        timeout=remaining,
                        deadline=deadline,
                        max_body_bytes=max_response_chars * 6 + 8192,
                        cancel=cancel,
                    )
                else:
                    resp = requests.post(
                        f"{endpoint}/chat/completions",
                        headers=headers,
                        json=payload,
                        timeout=remaining,
                    )
                    resp.raise_for_status()
                content = _response_text(resp, max_response_chars, deadline)
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
            if attempt < max_retries and not bounded:
                time.sleep(2**attempt)
        except requests.exceptions.RequestException as exc:
            logger.warning(
                "LLM request failed (%s, attempt %s/%s)",
                type(exc).__name__,
                attempt + 1,
                attempts,
            )
            if attempt < max_retries and not bounded:
                time.sleep(2**attempt)

    return ""


def llm_chat_structured(
    messages: list,
    model: str | None = None,
    temperature: float = 0.0,
    cache: bool = True,
) -> dict:
    """调用 LLM 并解析 JSON 响应。"""
    content = llm_chat(messages, model, temperature, cache=cache)
    if not content:
        return {}

    # 尝试提取 JSON
    json_match = re.search(
        r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", content, re.DOTALL
    )
    if json_match:
        content = json_match.group(1)

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        logger.warning(f"Failed to parse LLM JSON response: {content[:200]}")
        return {}
    if not isinstance(parsed, dict):
        logger.warning(
            "LLM structured response must be a JSON object, got %s",
            type(parsed).__name__,
        )
        return {}
    return parsed


def llm_chat_batch(
    prompts: list[list],
    model: str | None = None,
    temperature: float = 0.0,
    max_workers: int | None = None,
    desc: str = "",
) -> list[str]:
    """批量并发调用 LLM。"""
    llm_cfg = get_llm_config()
    configured_workers = max_workers or int(llm_cfg.get("max_workers", 4) or 4)
    max_workers = max(1, min(int(configured_workers), 16))
    results = [""] * len(prompts)

    def _call(i):
        msgs = prompts[i]
        return i, llm_chat(msgs, model, temperature)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(_call, i) for i in range(len(prompts))]
        for f in as_completed(futures):
            i, text = f.result()
            results[i] = text

    return results
