"""One per-original raw OCSR cache, not compounds, corrections or acceptance."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

from patent_sar_extractor.core.ocsr.cache_snapshot import snapshot_observations
from patent_sar_extractor.core.ocsr.smiles_cache import OBSERVATIONS_SQL

from .errors import WebError
from .files import SafeFiles, private_directory

MAX_BYTES = 64 * 1024 * 1024
MAX_RECORDS = 25000


def cache_path(state: Path, project: dict) -> Path:
    sha = project.get("sha256")
    if not isinstance(sha, str) or not re.fullmatch(r"[a-f0-9]{64}", sha):
        raise WebError(
            422, "source_identity", "Raw cache requires a verified original SHA."
        )
    root = private_directory(state / "analysis" / "ocsr-observations")
    return root / f"{sha}.sqlite"


def safe_snapshot(path: Path, *, optional: bool = True) -> bytes | None:
    try:
        content = SafeFiles(path.parent).read(path.name, max_bytes=MAX_BYTES)
    except WebError as exc:
        if (
            optional
            and exc.code == "asset_unavailable"
            and not path.is_symlink()
            and not path.exists()
        ):
            return None
        raise
    try:
        return snapshot_observations(
            content, max_bytes=MAX_BYTES, max_records=MAX_RECORDS
        )
    except (ValueError, sqlite3.DatabaseError) as exc:
        raise WebError(
            422, "recognition_cache", "Raw-observation cache failed bounded validation."
        ) from exc


def merge_snapshots(destination: Path, snapshots: list[bytes]) -> int:
    """Atomic, first-party-only merge; distinct raw strings under one key fail."""
    with closing(sqlite3.connect(":memory:")) as target:
        target.execute(OBSERVATIONS_SQL)
        for content in snapshots:
            with closing(sqlite3.connect(":memory:")) as source:
                source.deserialize(content)
                for row in source.execute(
                    "SELECT image_hash,engine,payload,created_at FROM smiles_observations"
                ):
                    old = target.execute(
                        "SELECT payload FROM smiles_observations WHERE image_hash=? AND engine=?",
                        row[:2],
                    ).fetchone()
                    if old and json.loads(old[0]).get("raw_smiles") != json.loads(
                        row[2]
                    ).get("raw_smiles"):
                        raise WebError(
                            422,
                            "recognition_cache_conflict",
                            "One exact image/model key has conflicting raw observations.",
                        )
                    target.execute(
                        "INSERT OR IGNORE INTO smiles_observations VALUES(?,?,?,?)", row
                    )
        total = target.execute("SELECT count(*) FROM smiles_observations").fetchone()[0]
        if total > MAX_RECORDS:
            raise WebError(
                413,
                "recognition_cache_limit",
                "Per-original observation cache exceeds its record limit.",
            )
        target.commit()
        content = target.serialize()
        if len(content) > MAX_BYTES:
            raise WebError(
                413,
                "recognition_cache_limit",
                "Per-original observation cache exceeds its byte limit.",
            )
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=destination.parent, prefix=".ocsr-", delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return total


def seed_job_cache(
    state: Path, project: dict, destination: Path, original: Path
) -> None:
    snapshots = []
    for path in (destination, original, cache_path(state, project)):
        snapshot = safe_snapshot(path) if path.parent.is_dir() else None
        if snapshot is not None:
            snapshots.append(snapshot)
    if snapshots:
        merge_snapshots(destination, snapshots)


def publish_job_cache(state: Path, project: dict, source: Path) -> int:
    snapshot = safe_snapshot(source)
    if snapshot is None:
        return 0
    target = cache_path(state, project)
    previous = safe_snapshot(target)
    return merge_snapshots(target, [*([previous] if previous else []), snapshot])


def import_observations(workspace, project_id: str, source: Path) -> dict:
    """Operator recovery: only raw observations, no table data/properties/QA."""
    from .analysis import AnalysisService
    from .pdf import open_pdf

    project = workspace.store.project(project_id)
    with open_pdf(workspace.store.root, project):
        pass
    analysis = AnalysisService(workspace.store.root, workspace)
    try:
        with analysis._operation(None):
            with workspace.store.connect() as db:
                if db.execute(
                    "SELECT 1 FROM jobs WHERE status IN ('queued','running')"
                ).fetchone():
                    raise WebError(
                        409,
                        "recognition_cache_busy",
                        "Finish active software jobs before raw cache recovery.",
                    )
            snapshot = safe_snapshot(source, optional=False)
            assert snapshot is not None
            target = cache_path(workspace.store.root, project)
            previous = safe_snapshot(target)
            count = merge_snapshots(
                target, [*([previous] if previous else []), snapshot]
            )
    finally:
        analysis.close()
    return {
        "original_sha256": project["sha256"],
        "raw_observations": count,
        "model_loaded": False,
        "compound_data_written": False,
        "acceptance_promoted": False,
    }
