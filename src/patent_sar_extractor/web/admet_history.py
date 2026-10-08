"""Bounded ADMET stage facts, source-job bound and write-once when terminal."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .attempts import spec_record
from .errors import WebError
from .files import SafeFiles, private_directory
from .models import Stage
from .processes import runtime_identity, runtime_identity_matches

SCHEMA = {"name": "patentsar.admet-job-stage", "version": 1}
TERMINAL = {"complete", "failed", "cancelled", "interrupted"}
MAX_BYTES = 16384


def _spec(row: dict[str, Any]) -> dict[str, Any]:
    if (
        not isinstance(row.get("id"), str)
        or not re.fullmatch(r"[a-f0-9]{32}", row["id"])
        or not isinstance(row.get("project_id"), str)
        or not re.fullmatch(r"[a-f0-9]{32}", row["project_id"])
    ):
        raise ValueError("ADMET history requires canonical workspace identities")
    spec = spec_record(row["spec"])
    if (
        spec.get("job_id") != row["id"]
        or spec.get("project_id") != row["project_id"]
        or spec.get("include_admet") is not True
        or not runtime_identity_matches(spec.get("runtime_identity"))
    ):
        raise ValueError("ADMET history does not belong to the producer specification")
    return spec


def _validate(stage: Stage, spec: dict[str, Any], core_completed: bool) -> None:
    if (
        stage.name != "admet"
        or stage.status not in {"pending", "running", "ok", "empty", "failed"}
        or type(core_completed) is not bool
        or (spec.get("admet_only", False) and core_completed)
        or (
            stage.status in {"running", "ok", "empty"}
            and not spec.get("admet_only", False)
            and not core_completed
        )
    ):
        raise ValueError("ADMET phase or core-completion evidence is invalid")
    progress = stage.progress
    if progress is not None and (
        stage.count != progress.completed - progress.failures
        or (stage.status != "failed" and progress.failures != 0)
    ):
        raise ValueError("ADMET stage count differs from its measured progress")
    if stage.status == "ok" and (
        progress is None
        or progress.total < 1
        or progress.completed != progress.total
        or progress.failures
    ):
        raise ValueError("An OK ADMET stage requires complete measured progress")
    if stage.status == "empty" and (
        progress is None
        or progress.total != 0
        or progress.completed != 0
        or progress.cache_hits
        or progress.failures
        or stage.count != 0
    ):
        raise ValueError("An empty ADMET stage must not claim predictions.")


def read_admet_stage(
    row: dict[str, Any], root: Path | None, *, state_root: Path | None = None
) -> tuple[Stage | None, bool]:
    if root is None:
        return None, False
    try:
        spec = _spec(row)
        terminal = state_root is not None and row["status"] in TERMINAL
        source = state_root if terminal else root
        assert source is not None
        filename = (
            f"job-history/{row['id']}-admet.json" if terminal else "admet-stage.json"
        )
        raw = json.loads(SafeFiles(source).read(filename, max_bytes=MAX_BYTES))
        keys = {
            "schema",
            "runtime_identity",
            "job_id",
            "project_id",
            "spec_sha256",
            "core_completed",
            "stage",
        }
        if terminal:
            keys |= {"status", "finished_at"}
        if (
            not isinstance(raw, dict)
            or set(raw) != keys
            or raw.get("schema") != SCHEMA
            or type(raw["schema"].get("version")) is not int
            or not runtime_identity_matches(raw.get("runtime_identity"))
            or raw.get("job_id") != row["id"]
            or raw.get("project_id") != row["project_id"]
            or raw.get("spec_sha256")
            != hashlib.sha256(row["spec"].encode()).hexdigest()
            or type(raw.get("core_completed")) is not bool
        ):
            return None, False
        if terminal and (
            raw["status"] != row["status"]
            or raw["finished_at"] != row["finished_at"]
            or not isinstance(raw["finished_at"], str)
            or datetime.fromisoformat(raw["finished_at"]).tzinfo is None
        ):
            return None, False
        stage = Stage.model_validate(raw["stage"])
        _validate(stage, spec, raw["core_completed"])
        if terminal and (
            stage.status in {"pending", "running"}
            or (row["status"] == "complete" and stage.status not in {"ok", "empty"})
        ):
            return None, False
        return stage, raw["core_completed"]
    except (
        WebError,
        ValueError,
        KeyError,
        TypeError,
        RecursionError,
        ValidationError,
        OSError,
    ):
        return None, False


def _payload(row: dict[str, Any], stage: Stage, core_completed: bool) -> dict[str, Any]:
    spec = _spec(row)
    stage = Stage.model_validate_json(stage.model_dump_json())
    _validate(stage, spec, core_completed)
    return {
        "schema": SCHEMA,
        "runtime_identity": runtime_identity(),
        "job_id": row["id"],
        "project_id": row["project_id"],
        "spec_sha256": hashlib.sha256(row["spec"].encode()).hexdigest(),
        "core_completed": core_completed,
        "stage": stage.model_dump(),
    }


def write_admet_stage(
    root: Path, row: dict[str, Any], stage: Stage, *, core_completed: bool
) -> None:
    payload = json.dumps(
        _payload(row, stage, core_completed), allow_nan=False, separators=(",", ":")
    ).encode()
    if len(payload) > MAX_BYTES:
        raise ValueError("ADMET history exceeds its bound")
    directory = private_directory(root)
    fd, name = tempfile.mkstemp(prefix="admet-stage-", dir=directory)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, directory / "admet-stage.json")
    finally:
        Path(name).unlink(
            missing_ok=True
        )  # This writer's own unpublished temporary only.


def seal_admet_stage(
    state_root: Path,
    root: Path,
    row: dict[str, Any],
    status: str,
    stamp: str,
    *,
    research_complete: bool = False,
) -> None:
    spec = _spec(row)
    if status not in TERMINAL or datetime.fromisoformat(stamp).tzinfo is None:
        raise ValueError("ADMET history needs an actual terminal status and timestamp")
    stage, completed = read_admet_stage(row, root)
    if stage is None:
        stage, completed = Stage(name="admet", status="failed"), False
    elif (status != "complete" and not research_complete) or stage.status in {
        "pending",
        "running",
    }:
        stage = stage.model_copy(update={"status": "failed"})
    if research_complete and (
        status != "failed" or not completed or stage.status not in {"ok", "empty"}
    ):
        raise ValueError(
            "Research completion cannot override missing or failed producer evidence"
        )
    if status == "complete" and stage.status not in {"ok", "empty"}:
        raise ValueError("Incomplete ADMET facts cannot be sealed as a successful task")
    _validate(stage, spec, completed)
    payload = _payload(row, stage, completed)
    payload.update(status=status, finished_at=stamp)
    data = json.dumps(payload, allow_nan=False, separators=(",", ":")).encode()
    if len(data) > MAX_BYTES:
        raise ValueError("Sealed ADMET history exceeds its bound")
    directory = private_directory(state_root / "job-history")
    fd = os.open(
        directory / f"{row['id']}-admet.json",
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
    )
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
