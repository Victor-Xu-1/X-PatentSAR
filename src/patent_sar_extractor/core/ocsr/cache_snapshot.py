"""Bounded transport of exact raw observations, never derived acceptance.

Rebuild only the first-party observation table from a read-only in-memory copy.
Foreign SQLite schema, triggers and legacy repaired results are not transported.
The converter remains the sole authority for image/model identity and current QC.
"""

from __future__ import annotations

import json
import re
import sqlite3
from contextlib import closing

from patent_sar_extractor.contracts import OCSR_OBSERVATION_VERSION

from .smiles_cache import OBSERVATIONS_SQL, SmilesCache

_HASH = re.compile(r"[0-9a-f]{64}\Z")
_ENGINE = re.compile(rf"decimer:raw-v{OCSR_OBSERVATION_VERSION}:([0-9a-f]{{64}})\Z")


def _invalid_constant(value: str) -> None:
    raise ValueError("Non-finite raw observation")


def _bounded_payload(payload: str) -> dict:
    if len(payload.encode("utf-8")) > SmilesCache.MAX_OBSERVATION_BYTES:
        raise ValueError("Raw observation exceeds its limit")
    result = json.loads(payload, parse_constant=_invalid_constant)
    if not isinstance(result, dict):
        raise ValueError("Raw observation is not an object")
    pending = [(result, 0)]
    while pending:
        value, depth = pending.pop()
        if depth > 40:
            raise ValueError("Raw observation nesting exceeds its limit")
        if isinstance(value, dict):
            pending.extend((item, depth + 1) for item in value.values())
        elif isinstance(value, list):
            pending.extend((item, depth + 1) for item in value)
    return result


def snapshot_observations(content: bytes, *, max_bytes: int, max_records: int) -> bytes:
    """Preserve current-epoch payloads exactly without trusting source SQL.

    This does not load a model, modify SMILES, or call anything accepted. Failed
    observations are omitted so the converter re-executes those inputs.
    """
    if not 0 < len(content) <= max_bytes or not 0 < max_records <= 25000:
        raise ValueError("Raw cache exceeds its transport limit")
    with (
        closing(sqlite3.connect(":memory:")) as source,
        closing(sqlite3.connect(":memory:")) as target,
    ):
        source.deserialize(content)
        source.execute("PRAGMA trusted_schema=OFF")
        source.execute("PRAGMA query_only=ON")
        remaining = 2000

        def exceeded() -> int:
            nonlocal remaining
            remaining -= 1
            return int(remaining < 0)

        source.set_progress_handler(exceeded, 1000)
        schema = source.execute(
            "SELECT type FROM sqlite_schema WHERE name='smiles_observations'"
        ).fetchone()
        if schema != ("table",):
            raise ValueError("Raw cache lacks its observation table")
        columns = source.execute("PRAGMA table_info(smiles_observations)").fetchall()
        if [row[1] for row in columns] != [
            "image_hash",
            "engine",
            "payload",
            "created_at",
        ]:
            raise ValueError("Raw cache observation schema is invalid")
        target.execute(OBSERVATIONS_SQL)
        rows = source.execute(
            "SELECT image_hash,engine,payload,created_at FROM smiles_observations LIMIT ?",
            (max_records + 1,),
        )
        for count, row in enumerate(rows, 1):
            if count > max_records:
                raise ValueError("Raw cache exceeds its record limit")
            image_hash, engine, payload, created_at = row
            if not all(isinstance(value, str) for value in row):
                raise ValueError("Raw cache observation fields are invalid")
            if not _HASH.fullmatch(image_hash) or len(engine) > 256:
                raise ValueError("Raw cache observation identity is invalid")
            match = _ENGINE.fullmatch(engine)
            if match is None:
                # Old repaired/unknown epochs are not observations in this contract.
                continue
            if len(created_at) > 64:
                raise ValueError("Raw cache observation timestamp is invalid")
            result = _bounded_payload(payload)
            if result.get("status") != "success":
                continue
            if result.get("model_fingerprint") != match.group(1):
                raise ValueError("Raw cache model identity is inconsistent")
            raw = result.get("raw_smiles")
            if raw is not None and not isinstance(raw, str):
                raise ValueError("Raw cache prediction is invalid")
            target.execute("INSERT INTO smiles_observations VALUES (?,?,?,?)", row)
        target.commit()
        snapshot = target.serialize()
        if len(snapshot) > max_bytes:
            raise ValueError("Raw cache snapshot exceeds its limit")
        return snapshot
