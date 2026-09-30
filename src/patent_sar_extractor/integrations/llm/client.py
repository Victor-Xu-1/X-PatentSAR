"""
LLM Client — 统一大模型调用客户端

对接 OpenAI 兼容协议 LLM，支持：
- 文本理解、QA 校验
- 线程池并发
- 结果缓存（SQLite）
"""

import json
import logging
import os
import hashlib
import re
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

import requests

from .config import get_llm_config

logger = logging.getLogger(__name__)

# ── 缓存 ──

def _get_cache_db():
    llm_cfg = get_llm_config()
    cache_path = str(llm_cfg.get("cache_path", "") or "")
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
) -> str:
    raw = json.dumps(
        {
            "messages": messages,
            "model": model,
            "temperature": temperature,
            "endpoint": endpoint,
            "max_tokens": max_tokens,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def _cached(key: str, ttl_hours: int = 24) -> Optional[str]:
    db = _get_cache_db()
    if db is None:
        return None
    try:
        row = db.execute(
            "SELECT response FROM llm_cache WHERE cache_key=? AND created_at>?",
            (key, time.time() - ttl_hours * 3600),
        ).fetchone()
        return row[0] if row else None
    finally:
        db.close()


def _cache_set(key: str, response: str) -> None:
    db = _get_cache_db()
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

def llm_chat(
    messages: list,
    model: str = None,
    temperature: float = 0.0,
    max_tokens: int = 4096,
    cache: bool = True,
    cache_ttl: int = 24,
) -> str:
    """调用 LLM，返回文本响应。"""
    llm_cfg = get_llm_config()
    model = model or str(llm_cfg.get("model", ""))
    endpoint = str(llm_cfg.get("endpoint", "")).rstrip("/")
    api_key = str(llm_cfg.get("api_key", "")).strip()
    timeout = int(llm_cfg.get("timeout", 180) or 180)
    use_cache = cache and temperature == 0.0

    if not api_key:
        logger.error("LLM_API_KEY is not set; skipping LLM request")
        return ""
    if not endpoint:
        logger.error("LLM endpoint is not set; skipping LLM request")
        return ""

    key = _cache_key(messages, model, temperature, endpoint, max_tokens)
    if use_cache:
        cached = _cached(key, cache_ttl)
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

    for attempt in range(3):
        try:
            resp = requests.post(
                f"{endpoint}/chat/completions",
                headers=headers,
                json=payload,
                timeout=timeout,
            )
            resp.raise_for_status()
            try:
                result = resp.json()
                raw_content = result["choices"][0]["message"]["content"]
                if not isinstance(raw_content, str):
                    raise TypeError("message content is not a string")
                content = raw_content.strip()
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                logger.error("LLM response parse failed: %s", exc)
                break

            if use_cache:
                _cache_set(key, content)

            return content
        except requests.exceptions.Timeout:
            logger.warning(f"LLM timeout (attempt {attempt + 1}/3)")
            if attempt < 2:
                time.sleep(2 ** attempt)
        except requests.exceptions.RequestException as e:
            logger.warning(f"LLM error (attempt {attempt + 1}/3): {e}")
            if attempt < 2:
                time.sleep(2 ** attempt)

    return ""


def llm_chat_structured(
    messages: list,
    model: str = None,
    temperature: float = 0.0,
    cache: bool = True,
) -> dict:
    """调用 LLM 并解析 JSON 响应。"""
    content = llm_chat(messages, model, temperature, cache=cache)
    if not content:
        return {}

    # 尝试提取 JSON
    json_match = re.search(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", content, re.DOTALL)
    if json_match:
        content = json_match.group(1)

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        logger.warning(f"Failed to parse LLM JSON response: {content[:200]}")
        return {}
    if not isinstance(parsed, dict):
        logger.warning("LLM structured response must be a JSON object, got %s", type(parsed).__name__)
        return {}
    return parsed


def llm_chat_batch(
    prompts: list[list],
    model: str = None,
    temperature: float = 0.0,
    max_workers: int = None,
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
