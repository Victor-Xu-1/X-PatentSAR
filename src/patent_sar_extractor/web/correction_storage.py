"""Separate correction/audit tables on the existing private SQLite v1 database."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any

from .correction_models import CorrectionDocument
from .errors import WebError
from .storage import Store, encode

_SCHEMA = (
    (
        "CREATE TABLE IF NOT EXISTS corrections ("
        "project_id TEXT NOT NULL REFERENCES projects(id), compound_id TEXT NOT NULL,"
        "basis_fingerprint TEXT NOT NULL, original_fields TEXT NOT NULL, fields TEXT NOT NULL,"
        "revision INTEGER NOT NULL CHECK(revision>0), updated_at TEXT NOT NULL,"
        "PRIMARY KEY(project_id,compound_id))"
    ),
    (
        "CREATE TABLE IF NOT EXISTS correction_audit ("
        "project_id TEXT NOT NULL REFERENCES projects(id), compound_id TEXT NOT NULL,"
        "basis_fingerprint TEXT NOT NULL, original_fields TEXT NOT NULL, fields TEXT NOT NULL,"
        "revision INTEGER NOT NULL CHECK(revision>0), updated_at TEXT NOT NULL,"
        "PRIMARY KEY(project_id,compound_id,revision))"
    ),
    (
        "CREATE TRIGGER IF NOT EXISTS correction_audit_no_update BEFORE UPDATE ON correction_audit "
        "BEGIN SELECT RAISE(ABORT,'Correction audit is immutable'); END"
    ),
    (
        "CREATE TRIGGER IF NOT EXISTS correction_audit_no_delete BEFORE DELETE ON correction_audit "
        "BEGIN SELECT RAISE(ABORT,'Correction audit is immutable'); END"
    ),
)

# A single joined read supplies overlays without a per-compound database query.
CORRECTION_COLUMNS = (
    ",e.basis_fingerprint AS correction_basis,e.original_fields AS correction_original,"
    "e.fields AS correction_fields,e.revision AS correction_revision,"
    "e.updated_at AS correction_updated_at "
)
CORRECTION_JOIN = (
    "LEFT JOIN corrections e ON c.project_id=e.project_id AND c.id=e.compound_id "
)


def correction_source_fingerprint(
    project: dict[str, Any], raw_compound_row: dict[str, Any]
) -> str:
    """Canonical raw row plus original/run/projection identity, never review timestamps."""
    snapshot = json.loads(project["snapshot"])
    source = {
        "project_id": project["id"],
        "original_sha256": project["sha256"] or project["expected_sha256"],
        "original_path": project["pdf_rel"],
        "page_count": project["page_count"],
        "run_root": project["run_root"],
        "import_key": project["import_key"],
        "projection_id": snapshot.get("correction_projection_id"),
        "read_model_identity": snapshot.get("read_model_identity"),
        "row": {
            "payload": json.loads(raw_compound_row["payload"]),
            "ordinal": raw_compound_row["ordinal"],
            "image_path": raw_compound_row["image_path"],
            "geometry_space": raw_compound_row["geometry_space"],
        },
    }
    canonical = json.dumps(source, ensure_ascii=False, sort_keys=True, allow_nan=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def joined_correction(row: dict[str, Any]) -> dict[str, Any] | None:
    if row.get("correction_revision") is None:
        return None
    return {
        "basis_fingerprint": row["correction_basis"],
        "original_fields": row["correction_original"],
        "fields": row["correction_fields"],
        "revision": row["correction_revision"],
        "updated_at": row["correction_updated_at"],
    }


class CorrectionStorage:
    def __init__(self, store: Store) -> None:
        self.store = store
        with store.connect(write=True) as connection:
            for statement in _SCHEMA:
                connection.execute(statement)

    @staticmethod
    def context(
        connection: sqlite3.Connection, project_id: str, compound_id: str
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any] | None]:
        project = connection.execute(
            "SELECT * FROM projects WHERE id=?", (project_id,)
        ).fetchone()
        if project is None:
            raise WebError(404, "project_not_found", "Project does not exist.")
        row = connection.execute(
            "SELECT * FROM compounds WHERE project_id=? AND id=?",
            (project_id, compound_id),
        ).fetchone()
        if row is None:
            raise WebError(
                404,
                "compound_not_found",
                "Compound is not in the activity-led result set.",
            )
        saved = connection.execute(
            "SELECT * FROM corrections WHERE project_id=? AND compound_id=?",
            (project_id, compound_id),
        ).fetchone()
        return dict(project), dict(row), dict(saved) if saved is not None else None

    @staticmethod
    def write(
        connection: sqlite3.Connection,
        project_id: str,
        compound_id: str,
        document: CorrectionDocument,
    ) -> None:
        values = (
            project_id,
            compound_id,
            document.basis_fingerprint,
            encode(document.original.model_dump()),
            encode(document.values.model_dump()),
            document.revision,
            document.updated_at,
        )
        connection.execute(
            "INSERT INTO corrections VALUES(?,?,?,?,?,?,?) "
            "ON CONFLICT(project_id,compound_id) DO UPDATE SET "
            "basis_fingerprint=excluded.basis_fingerprint,original_fields=excluded.original_fields,"
            "fields=excluded.fields,revision=excluded.revision,updated_at=excluded.updated_at",
            values,
        )
        connection.execute("INSERT INTO correction_audit VALUES(?,?,?,?,?,?,?)", values)
        connection.execute(
            "UPDATE projects SET updated_at=? WHERE id=?",
            (document.updated_at, project_id),
        )
