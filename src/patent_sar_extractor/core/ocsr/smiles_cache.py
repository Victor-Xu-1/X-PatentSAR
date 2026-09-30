"""
SMILES Cache module using SQLite.

Caches OCSR engine results by image SHA-256 hash + engine name
to avoid redundant inference on repeated runs.
"""

import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Optional

from .smiles_qc import qc_smiles


def compute_image_sha256(image_path: str) -> str:
    """Compute SHA-256 hash of an image file.

    Args:
        image_path: Path to image file.

    Returns:
        Hex-encoded SHA-256 hash string.
    """
    sha256 = hashlib.sha256()
    with open(image_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


class SmilesCache:
    """SQLite-based cache for OCSR engine results."""

    def __init__(self, cache_path: str):
        """Initialize cache.

        Args:
            cache_path: Path to SQLite database file.
                       Parent directories will be created automatically.
        """
        self.cache_path = cache_path
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        self._init_db()

    def _init_db(self):
        """Create cache table if not exists."""
        with sqlite3.connect(self.cache_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS smiles_cache (
                    image_hash TEXT NOT NULL,
                    engine TEXT NOT NULL,
                    raw_smiles TEXT,
                    molblock TEXT,
                    rdkit_valid INTEGER,
                    canonical_smiles TEXT,
                    inchikey TEXT,
                    mol_formula TEXT,
                    mol_weight REAL,
                    quality_flag TEXT,
                    status TEXT,
                    error TEXT,
                    model_version TEXT,
                    created_at TEXT,
                    PRIMARY KEY (image_hash, engine)
                )
            """)
            conn.commit()

    def get_cached_result(self, image_hash: str, engine: str) -> Optional[dict]:
        """Look up cached result for an image + engine combination.

        Args:
            image_hash: SHA-256 hash of the image file.
            engine: Engine name (production uses 'decimer').

        Returns:
            Cached result dict or None if not found.
        """
        with sqlite3.connect(self.cache_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM smiles_cache WHERE image_hash = ? AND engine = ?",
                (image_hash, engine),
            )
            row = cursor.fetchone()
            if row is None:
                return None

            result = dict(row)
            # Convert INTEGER back to bool
            if "rdkit_valid" in result and result["rdkit_valid"] is not None:
                result["rdkit_valid"] = bool(result["rdkit_valid"])
            return result

    def save_result(self, image_hash: str, engine: str, result: dict):
        """Save an engine result to cache.

        Args:
            image_hash: SHA-256 hash of the image file.
            engine: Engine name.
            result: Result dict from engine + QC.
        """
        now = datetime.now(timezone.utc).isoformat()

        with sqlite3.connect(self.cache_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO smiles_cache
                    (image_hash, engine, raw_smiles, molblock, rdkit_valid,
                     canonical_smiles, inchikey, mol_formula, mol_weight,
                     quality_flag, status, error, model_version, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    image_hash,
                    engine,
                    result.get("raw_smiles"),
                    result.get("molblock"),
                    int(result.get("rdkit_valid", False)),
                    result.get("canonical_smiles"),
                    result.get("inchikey"),
                    result.get("mol_formula"),
                    result.get("mol_weight"),
                    result.get("quality_flag"),
                    result.get("status"),
                    result.get("error"),
                    result.get("model_version"),
                    now,
                ),
            )
            conn.commit()

    def get_stats(self) -> dict:
        """Get cache statistics."""
        with sqlite3.connect(self.cache_path) as conn:
            total = conn.execute("SELECT COUNT(*) FROM smiles_cache").fetchone()[0]
            by_engine = dict(
                conn.execute(
                    "SELECT engine, COUNT(*) FROM smiles_cache GROUP BY engine"
                ).fetchall()
            )
            by_status = dict(
                conn.execute(
                    "SELECT status, COUNT(*) FROM smiles_cache GROUP BY status"
                ).fetchall()
            )
            valid = conn.execute(
                "SELECT COUNT(*) FROM smiles_cache WHERE rdkit_valid = 1"
            ).fetchone()[0]

        return {
            "total_entries": total,
            "valid_entries": valid,
            "by_engine": by_engine,
            "by_status": by_status,
        }

    def purge_non_clean(self) -> int:
        """Delete cache entries that cannot be reused as strict clean results.

        The database can contain rows created by older plugin releases whose
        stored quality fields were too permissive. Re-run current QC on the raw
        SMILES before trusting any row, so legacy/cache-seeded suspicious atoms
        cannot bypass the strict export gate.
        """
        with sqlite3.connect(self.cache_path) as conn:
            conn.row_factory = sqlite3.Row
            before = conn.execute("SELECT COUNT(*) FROM smiles_cache").fetchone()[0]
            conn.execute(
                """
                DELETE FROM smiles_cache
                WHERE raw_smiles IS NULL
                   OR TRIM(raw_smiles) = ''
                   OR rdkit_valid != 1
                   OR quality_flag != 'ok'
                   OR status != 'success'
                """
            )
            stale_keys = []
            for row in conn.execute("SELECT image_hash, engine, raw_smiles FROM smiles_cache"):
                qc = qc_smiles(row["raw_smiles"])
                if not (
                    qc.get("rdkit_valid")
                    and qc.get("quality_flag") == "ok"
                    and not qc.get("suspicious_elements")
                    and not qc.get("has_dummy_atom")
                    and not qc.get("has_query_atom")
                ):
                    stale_keys.append((row["image_hash"], row["engine"]))
            if stale_keys:
                conn.executemany(
                    "DELETE FROM smiles_cache WHERE image_hash = ? AND engine = ?",
                    stale_keys,
                )
            conn.commit()
            after = conn.execute("SELECT COUNT(*) FROM smiles_cache").fetchone()[0]
        return int(before - after)
