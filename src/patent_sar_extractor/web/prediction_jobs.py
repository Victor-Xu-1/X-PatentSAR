"""Targeted recalculation uses the existing durable queue and its one consumer."""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import asdict

from .attempts import ATTEMPT_VERSION
from .errors import WebError
from .files import private_directory
from .models import Compound
from .processes import RunSpec, runtime_identity
from .storage import Store, encode, now


def enqueue_prediction(
    store: Store,
    connection: sqlite3.Connection,
    project_id: str,
    *,
    compound_ids: tuple[str, ...] = (),
) -> str:
    project = connection.execute(
        "SELECT * FROM projects WHERE id=?", (project_id,)
    ).fetchone()
    if project is None:
        raise WebError(404, "project_not_found", "Project does not exist.")
    if not project["pdf_rel"] or not project["run_root"]:
        raise WebError(
            409,
            "admet_source_required",
            "Verified original and extracted structures are required.",
        )
    if connection.execute(
        "SELECT 1 FROM jobs WHERE project_id=? AND status IN ('queued','running')",
        (project_id,),
    ).fetchone():
        raise WebError(409, "job_active", "A project task is already active.")
    if (
        connection.execute(
            "SELECT COUNT(*) FROM jobs WHERE status='queued'"
        ).fetchone()[0]
        >= 100
    ):
        raise WebError(413, "queue_limit", "The task queue reached its limit.")
    job_id = uuid.uuid4().hex
    output = store.root / "runs" / project_id / job_id
    if output.exists() or any(path.is_symlink() for path in (output, *output.parents)):
        raise WebError(
            409,
            "unsafe_workspace",
            "Prediction output must be a new private job directory.",
        )
    private_directory(output)
    spec = RunSpec(
        job_id,
        project_id,
        str(store.root / project["pdf_rel"]),
        str(output),
        project["patent_id"],
        project["sha256"],
        include_admet=True,
        admet_only=True,
        admet_compounds=compound_ids,
    )
    payload = {
        **asdict(spec),
        "runtime_identity": runtime_identity(),
        "attempt_version": ATTEMPT_VERSION,
        "resume_job_id": None,
    }
    connection.execute(
        "INSERT INTO jobs(id,project_id,status,created_at,spec) VALUES(?,?,?,?,?)",
        (job_id, project_id, "queued", now(), encode(payload)),
    )
    # Intentionally do not replace run_root, compounds or the projection nonce.
    return job_id


def correction_prediction(
    store: Store,
    connection: sqlite3.Connection,
    project_id: str,
    compound_id: str,
    compound: Compound,
) -> None:
    if compound.smiles is not None:
        enqueue_prediction(store, connection, project_id, compound_ids=(compound_id,))
