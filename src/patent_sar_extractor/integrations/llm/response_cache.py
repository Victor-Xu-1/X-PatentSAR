"""Private bounded API response cache, not an acceptance or prediction store."""

from __future__ import annotations

import errno
import hashlib
import json
import os
import sqlite3
import stat
import time
from pathlib import Path

from .config import get_llm_config
from .private_state import private_root


def _get_cache_db(cache_path: str | None = None) -> sqlite3.Connection | None:
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
    # Optional cache contention must not consume the API's absolute deadline.
    db = sqlite3.connect(path, timeout=0)
    try:
        db.execute(
            "CREATE TABLE IF NOT EXISTS llm_cache (cache_key TEXT PRIMARY KEY, response TEXT, created_at REAL)"
        )
        db.commit()
    except BaseException:
        db.close()
        raise
    return db


def is_cache_unavailable(error: sqlite3.Error | OSError) -> bool:
    """Only ordinary lock/storage failures are optional, never unsafe access."""
    if isinstance(error, OSError):
        return error.errno in {
            errno.EIO,
            errno.ENOSPC,
            errno.EDQUOT,
            errno.EBUSY,
            errno.EAGAIN,
        }
    code = getattr(error, "sqlite_errorcode", None)
    if code is not None:
        if code in {sqlite3.SQLITE_IOERR_ACCESS, sqlite3.SQLITE_IOERR_AUTH}:
            return False
        return (code & 0xFF) in {
            sqlite3.SQLITE_BUSY,
            sqlite3.SQLITE_LOCKED,
            sqlite3.SQLITE_IOERR,
            sqlite3.SQLITE_FULL,
        }
    # Controlled adapters can raise SQLite exceptions without native codes.
    return isinstance(error, sqlite3.OperationalError) and str(error) in {
        "database is locked",
        "database table is locked",
        "disk I/O error",
        "database or disk is full",
    }


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
    validation_identity: str = "",
) -> str:
    if (
        not isinstance(validation_identity, str)
        or len(validation_identity) > 256
        or any(ord(char) < 32 for char in validation_identity)
    ):
        raise ValueError("Invalid API content-validation identity")
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
    if validation_identity:
        identity["validation_identity"] = validation_identity
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


def _cache_discard(key: str, response: str, *, cache_path: str | None = None) -> None:
    """Evict exactly the rejected observation, not a concurrent replacement."""
    db = _get_cache_db(cache_path)
    if db is None:
        return
    try:
        db.execute(
            "DELETE FROM llm_cache WHERE cache_key=? AND response=?", (key, response)
        )
        db.commit()
    finally:
        db.close()
