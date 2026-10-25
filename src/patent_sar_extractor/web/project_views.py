"""Readable project identities are independent of scientific result admission."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from .errors import WebError
from .history_storage import ensure_project_visible, tombstone
from .models import Acceptance, Error, PDFInfo, Project, Summary

if TYPE_CHECKING:
    from .service import WorkspaceService


# Only known saved-source read refusals become explicit unavailable metadata.
# Authentication, visibility, concurrency and unexpected failures still escape.
_SOURCE_READ_REFUSALS = frozenset(
    {
        (400, "unsafe_directory"),
        (400, "unsafe_asset"),
        (404, "asset_unavailable"),
        (413, "asset_limit"),
        (422, "artifact_limit"),
        (422, "invalid_artifact"),
        (422, "invalid_evidence"),
        (422, "invalid_source_recognition"),
        (422, "source_identity"),
    }
)


def project_view(service: WorkspaceService, project_id: str) -> Project:
    try:
        row = service._current_project(project_id)
    except WebError as error:
        if (error.status, error.code) not in _SOURCE_READ_REFUSALS:
            raise
        # Recheck visibility after the failed read. A concurrently deleted
        # project must not reappear through its retained source metadata.
        row = service.store.project(project_id)
        return Project(
            **_identity(row),
            is_historical=True,
            summary=Summary(),
            acceptance=Acceptance(state="failed", errors=[error.message]),
            last_job=None,
            read_error=Error(code=error.code, message=error.message),
        )
    return _available_project(service, row)


def _identity(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "title": row["title"],
        "patent_id": row["patent_id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "pdf": PDFInfo(
            available=bool(row["pdf_rel"]),
            page_count=row["page_count"],
            sha256=row["sha256"] or row["expected_sha256"],
        ),
    }


def _available_project(service: WorkspaceService, row: dict[str, Any]) -> Project:
    project_id = row["id"]
    snapshot = json.loads(row["snapshot"])
    with service.store.connect() as connection:
        connection.execute("BEGIN")
        ensure_project_visible(connection, project_id)
        latest = connection.execute(
            "SELECT * FROM jobs WHERE project_id=? ORDER BY created_at DESC,rowid DESC LIMIT 1",
            (project_id,),
        ).fetchone()
        latest_deleted = (
            latest is not None
            and tombstone(connection, "job", latest["id"])["deleted_at"] is not None
        )
        review_counts = connection.execute(
            "SELECT COUNT(c.id) AS total, "
            "COALESCE(SUM(CASE WHEN r.decision IN ('approved','rejected') "
            "THEN 1 ELSE 0 END),0) AS decided "
            "FROM compounds c LEFT JOIN reviews r "
            "ON r.project_id=c.project_id AND r.compound_id=c.id "
            "WHERE c.project_id=?",
            (project_id,),
        ).fetchone()
    first_structure = snapshot.get("first_structure_page")
    if type(first_structure) is not int or not 1 <= first_structure <= min(
        row["page_count"] or 20000, 20000
    ):
        first_structure = None
    retained_job = service._job(dict(latest)) if latest else None
    return Project(
        **_identity(row),
        is_historical=bool(row["historical"]),
        summary=Summary.model_validate(
            {
                **snapshot.get("summary", {}),
                "manually_reviewed": review_counts["decided"],
                "manual_review_pending": review_counts["total"]
                - review_counts["decided"],
            }
        ),
        acceptance=service._project_acceptance(row, dict(latest) if latest else None),
        last_job=retained_job if not latest_deleted else None,
        first_structure_page=first_structure,
    )
