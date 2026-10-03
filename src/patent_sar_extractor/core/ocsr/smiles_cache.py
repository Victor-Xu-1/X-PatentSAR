"""Private exact-observation cache; legacy tables are retained but never promoted."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .smiles_qc import qc_smiles

OBSERVATIONS_SQL = (
    "CREATE TABLE IF NOT EXISTS smiles_observations "
    "(image_hash TEXT NOT NULL,engine TEXT NOT NULL,payload TEXT NOT NULL,"
    "created_at TEXT NOT NULL,PRIMARY KEY(image_hash,engine))"
)


def compute_image_sha256(image_path: str) -> str:
    digest = hashlib.sha256()
    with open(image_path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class SmilesCache:
    MAX_OBSERVATION_BYTES = 65536

    def __init__(self, cache_path: str):
        self.cache_path = cache_path
        Path(cache_path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(cache_path) as connection:
            connection.execute(OBSERVATIONS_SQL)

    def get_cached_result(self, image_hash: str, engine: str) -> dict | None:
        with sqlite3.connect(self.cache_path) as connection:
            row = connection.execute(
                "SELECT payload FROM smiles_observations WHERE image_hash=? AND engine=?",
                (image_hash, engine),
            ).fetchone()
        if row is None:
            return None
        if len(row[0].encode("utf-8")) > self.MAX_OBSERVATION_BYTES:
            raise ValueError("OCSR cache observation exceeds its limit")
        payload = json.loads(row[0])
        if not isinstance(payload, dict):
            raise ValueError("OCSR cache observation is not an object")
        return payload

    def save_result(self, image_hash: str, engine: str, result: dict) -> None:
        payload = json.dumps(result, ensure_ascii=False, allow_nan=False)
        if len(payload.encode("utf-8")) > self.MAX_OBSERVATION_BYTES:
            raise ValueError("OCSR cache observation exceeds its limit")
        with sqlite3.connect(self.cache_path) as connection:
            connection.execute(
                "INSERT OR REPLACE INTO smiles_observations VALUES (?,?,?,?)",
                (image_hash, engine, payload, datetime.now(timezone.utc).isoformat()),
            )

    def get_stats(self) -> dict:
        with sqlite3.connect(self.cache_path) as connection:
            total = connection.execute(
                "SELECT COUNT(*) FROM smiles_observations"
            ).fetchone()[0]
            by_engine = dict(
                connection.execute(
                    "SELECT engine,COUNT(*) FROM smiles_observations GROUP BY engine"
                )
            )
            by_status = dict(
                connection.execute(
                    "SELECT json_extract(payload,'$.status'),COUNT(*) FROM smiles_observations GROUP BY json_extract(payload,'$.status')"
                )
            )
            valid = connection.execute(
                "SELECT COUNT(*) FROM smiles_observations WHERE json_extract(payload,'$.rdkit_valid')=1"
            ).fetchone()[0]
        return {
            "total_entries": total,
            "valid_entries": valid,
            "by_engine": by_engine,
            "by_status": by_status,
        }

    def purge_non_clean(self) -> int:
        """Only evict this rebuildable cache's non-clean observations, not history."""
        stale = []
        with sqlite3.connect(self.cache_path) as connection:
            for image_hash, engine, payload in connection.execute(
                "SELECT image_hash,engine,payload FROM smiles_observations"
            ):
                result = json.loads(payload)
                checked = qc_smiles(result.get("raw_smiles"))
                if result.get("status") != "success" or checked["quality_flag"] != "ok":
                    stale.append((image_hash, engine))
            connection.executemany(
                "DELETE FROM smiles_observations WHERE image_hash=? AND engine=?", stale
            )
        return len(stale)
