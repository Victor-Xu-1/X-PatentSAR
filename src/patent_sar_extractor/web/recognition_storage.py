"""Rebuildable, source-bound observations; never rewrite extraction or user audit."""

from __future__ import annotations

import hashlib
import json
import os
import threading
from collections import OrderedDict
from pathlib import Path

from patent_sar_extractor.core.ocsr.reprint_consistency import (
    REPRINT_REVIEW_FLAG,
)

from .errors import WebError
from .files import SafeFiles
from .models import Compound, Recognition
from .molecule_drawing import drawing_url
from .processes import runtime_identity, runtime_identity_matches
from .recognition_observations import _saved_observation
from .recognition_sources import (
    recognition_sources,
    source_context,
    source_image_digest,
    source_revision,
)
from .storage import Store, encode, now

RECOGNITION_COLUMNS = (
    ",g.source_fingerprint AS recognition_source,g.crop_sha256 AS recognition_crop,"
    "g.runtime_identity AS recognition_runtime,g.observation AS recognition_observation "
)
RECOGNITION_JOIN = "LEFT JOIN compound_recognitions g ON c.project_id=g.project_id AND c.id=g.compound_id "
_hashes: OrderedDict[tuple, str] = OrderedDict()
_hash_lock = threading.Lock()


def crop_digest(root: Path, path: str) -> str:
    """No-symlink descriptor reads; bounded stat cache avoids hashing every poll."""
    with SafeFiles(root).open(path, max_bytes=16 * 1024 * 1024) as stream:
        info = os.fstat(stream.fileno())
        key = (
            str(root),
            path,
            info.st_dev,
            info.st_ino,
            info.st_size,
            info.st_mtime_ns,
            info.st_ctime_ns,
        )
        with _hash_lock:
            cached = _hashes.get(key)
            if cached:
                _hashes.move_to_end(key)
                return cached
        content = stream.read(16 * 1024 * 1024 + 1)
        after = os.fstat(stream.fileno())
        if len(content) > 16 * 1024 * 1024 or (
            info.st_ino,
            info.st_size,
            info.st_mtime_ns,
            info.st_ctime_ns,
        ) != (after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise WebError(
                409,
                "recognition_source_changed",
                "Structure image changed while being read.",
            )
    digest = hashlib.sha256(content).hexdigest()
    with _hash_lock:
        _hashes[key] = digest
        while len(_hashes) > 1024:
            _hashes.popitem(last=False)
    return digest


def apply_recognition(project: dict, row: dict, compound: Compound) -> Compound:
    from .correction_storage import correction_source_fingerprint

    content = row.get("recognition_observation")
    if content is None:
        from .core_recognition_source import core_source_current

        if not core_source_current(project, row, compound):
            compound.smiles = None
            compound.redraw_image_url = None
            compound.recognition = Recognition(
                status="unavailable", quality_flag="source_image_changed"
            )
        return compound
    try:
        current = row["recognition_source"] == correction_source_fingerprint(
            project, row
        ) and runtime_identity_matches(json.loads(row["recognition_runtime"]))
    except (ValueError, TypeError):
        current = False
    if current:
        try:
            current = row["recognition_crop"] == crop_digest(
                Path(project["run_root"]), row["image_path"]
            )
            binding, revision = recognition_sources(project, compound.id)
            if binding is None:
                raise WebError(
                    409,
                    "recognition_source_changed",
                    "Recognition no longer has a proved original source owner.",
                )
            context = source_context(binding, str(project["run_root"]))
            recognition, smiles, digest = _saved_observation(
                content, compound.id, compound.structure_id, context
            )
            current = current and (
                digest is None or digest == source_image_digest(project, binding)
            )
            current = current and source_revision(project) == revision
        except WebError:
            current = False
    if not current:
        compound.smiles = None
        compound.redraw_image_url = None
        compound.recognition = Recognition(
            status="unavailable", quality_flag="completion_source_changed"
        )
        return compound
    compound.recognition = recognition.model_copy(deep=True)
    compound.smiles = smiles
    if recognition.status == "valid":
        compound.flags = [
            flag for flag in compound.flags if flag != REPRINT_REVIEW_FLAG
        ]
    elif (
        recognition.quality_flag == REPRINT_REVIEW_FLAG
        and REPRINT_REVIEW_FLAG not in compound.flags
    ):
        compound.flags.append(REPRINT_REVIEW_FLAG)
    compound.redraw_image_url = (
        drawing_url(project["id"], compound.id, compound.smiles)
        if compound.smiles
        else None
    )
    return compound


def _require_active_producer(job, project_id: str, compound_id: str) -> None:
    try:
        spec = json.loads(job["spec"]) if job else {}
    except (ValueError, TypeError):
        spec = {}
    if not isinstance(spec, dict):
        spec = {}
    selection = spec.get("admet_compounds", [])
    if (
        not job
        or job["project_id"] != project_id
        or job["status"] != "running"
        or job["cancel_requested"]
        or spec.get("job_id") != job["id"]
        or spec.get("project_id") != project_id
        or spec.get("include_admet") is not True
        or not runtime_identity_matches(spec.get("runtime_identity"))
        or not isinstance(selection, list)
        or any(not isinstance(item, str) for item in selection)
        or (selection and compound_id not in selection)
    ):
        raise WebError(
            409, "recognition_cancelled", "Recognition job is no longer active."
        )


class RecognitionStore:
    def __init__(self, store: Store) -> None:
        self.store = store
        with store.connect(write=True) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS compound_recognitions ("
                "project_id TEXT NOT NULL REFERENCES projects(id),compound_id TEXT NOT NULL,"
                "source_fingerprint TEXT NOT NULL,crop_sha256 TEXT NOT NULL,"
                "runtime_identity TEXT NOT NULL,observation TEXT NOT NULL,"
                "job_id TEXT NOT NULL REFERENCES jobs(id),updated_at TEXT NOT NULL,"
                "PRIMARY KEY(project_id,compound_id))"
            )

    def put(
        self,
        project_id: str,
        compound_id: str,
        *,
        source: str,
        crop: str,
        record: dict,
        job_id: str,
    ) -> None:
        from .correction_storage import correction_source_fingerprint

        _require_active_producer(self.store.job(job_id), project_id, compound_id)
        snapshot = self.store.project(project_id)
        binding, revision = recognition_sources(snapshot, compound_id)
        if binding is None:
            raise WebError(
                409,
                "recognition_source_changed",
                "Recognition no longer has a proved original source owner.",
            )
        encoded = encode(record)
        _saved_observation(
            encoded,
            compound_id,
            binding.get("structure_id"),
            source_context(binding, str(snapshot["run_root"])),
        )
        digest = source_image_digest(snapshot, binding, record)
        with self.store.connect(write=True) as connection:
            job = connection.execute(
                "SELECT * FROM jobs WHERE id=?", (job_id,)
            ).fetchone()
            _require_active_producer(job, project_id, compound_id)
            project = dict(
                connection.execute(
                    "SELECT * FROM projects WHERE id=?", (project_id,)
                ).fetchone()
            )
            raw = connection.execute(
                "SELECT * FROM compounds WHERE project_id=? AND id=?",
                (project_id, compound_id),
            ).fetchone()
            if not raw:
                raise WebError(
                    409,
                    "recognition_source_changed",
                    "Numbered source is no longer present.",
                )
            raw = dict(raw)
            if (
                project["run_root"] != snapshot["run_root"]
                or source_revision(project) != revision
                or (
                    digest is not None
                    and digest != source_image_digest(project, binding)
                )
                or source != correction_source_fingerprint(project, raw)
                or crop != crop_digest(Path(project["run_root"]), raw["image_path"])
            ):
                raise WebError(
                    409,
                    "recognition_source_changed",
                    "Recognition input changed before publication.",
                )
            compound = Compound.model_validate_json(raw["payload"])
            if (
                record.get("cpd_id") != compound.id
                or record.get("structure_id") != compound.structure_id
            ):
                raise WebError(
                    422,
                    "recognition_owner",
                    "Recognition belongs to another numbered source.",
                )
            connection.execute(
                "INSERT INTO compound_recognitions VALUES(?,?,?,?,?,?,?,?) "
                "ON CONFLICT(project_id,compound_id) DO UPDATE SET "
                "source_fingerprint=excluded.source_fingerprint,crop_sha256=excluded.crop_sha256,"
                "runtime_identity=excluded.runtime_identity,observation=excluded.observation,"
                "job_id=excluded.job_id,updated_at=excluded.updated_at",
                (
                    project_id,
                    compound_id,
                    source,
                    crop,
                    encode(runtime_identity()),
                    encoded,
                    job_id,
                    now(),
                ),
            )
