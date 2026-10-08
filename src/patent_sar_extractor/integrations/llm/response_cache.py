"""Private bounded API response cache, not an acceptance or prediction store."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
import time
from pathlib import Path

from .config import get_llm_config
from .private_state import private_root


def _get_cache_db(cache_path: str | None = None):
    if cache_path is None:
        cache_path = str(get_llm_config().get("cache_path", "") or "")
    if not cache_path:
        return None
    path = Path(cache_path)
    directory = path.parent.absolute()
    private_root(directory)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        info = path.lstat()
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_mode & 0o077
            or info.st_nlink != 1
            or info.st_size > 64 * 1024 * 1024
        ):
            raise ValueError("Unsafe or excessive API cache")
    else:
        os.close(fd)
    db = sqlite3.connect(path, timeout=10)
    db.execute(
        "CREATE TABLE IF NOT EXISTS llm_cache (cache_key TEXT PRIMARY KEY, response TEXT, created_at REAL)"
    )
    db.commit()
    return db


def _cache_key(
    messages: list,
    model: str,
    temperature: float,
    endpoint: str = "",
    max_tokens: int = 1024,
    response_format: dict | None = None,
    max_response_chars: int | None = None,
    protocol: str = "openai-compatible",
    response_mode: str = "json-schema",
) -> str:
    identity = {
        "messages": messages,
        "model": model,
        "temperature": temperature,
        "endpoint": endpoint,
        "max_tokens": max_tokens,
        "protocol": protocol,
        "response_mode": response_mode,
    }
    if response_format is not None or max_response_chars is not None:
        identity.update(
            response_format=response_format, max_response_chars=max_response_chars
        )
    return hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()[:32]


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
            "SELECT response FROM llm_cache WHERE cache_key=? AND created_at>? AND (? IS NULL OR length(response)<=?)",
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
        db.execute("DELETE FROM llm_cache WHERE created_at < ?", (time.time() - 86400,))
        db.execute(
            "DELETE FROM llm_cache WHERE cache_key IN (SELECT cache_key FROM llm_cache ORDER BY created_at DESC LIMIT -1 OFFSET 10000)"
        )
        db.commit()
    finally:
        db.close()
