"""Workspace use cases shared by HTTP and controller-owned CLI commands."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from .artifacts import ArtifactView
from .errors import WebError
from .models import (
    Acceptance,
    Compound,
    Error,
    Job,
    PDFInfo,
    Project,
    Results,
    Summary,
)
from .pdf import UploadedPDF, copy_original, filename_title
from .processes import runtime_identity
from .result_queries import ResultQueries
from .stages import read_stages
from .storage import Store, encode, now
from .task_inputs import patent_identifier


class WorkspaceService:
    def __init__(self, state_root: str | Path) -> None:
        self.store = Store(state_root)
        self.result_queries = ResultQueries(self.store)

    @staticmethod
    def _title(title: str) -> str:
        title = title.strip()
        if not title or len(title) > 200 or any(ord(c) < 32 for c in title):
            raise WebError(
                400,
                "invalid_title",
                "Project title must be 1–200 characters without control characters.",
            )
        return title

    def add_pdf(
        self,
        uploaded: UploadedPDF,
        filename: str,
        title: str | None,
        patent_id: str | None = None,
    ) -> Project:
        stem, inferred_id = filename_title(filename)
        patent_id = patent_identifier(patent_id) if patent_id else inferred_id
        title = self._title(title or stem)
        project_id = uuid.uuid4().hex
        stamp = now()
        snapshot = {
            "summary": Summary().model_dump(),
            "acceptance": Acceptance(state="not_run").model_dump(),
            "is_historical": False,
            "metrics": [],
            "targets": [],
        }
        try:
            with self.store.connect(write=True) as connection:
                if (
                    connection.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
                    >= 200
                ):
                    raise WebError(
                        413, "project_limit", "Workspace has reached its project limit."
                    )
                connection.execute(
                    "INSERT INTO projects(id,title,patent_id,created_at,updated_at,pdf_rel,sha256,expected_sha256,page_count,snapshot) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (
                        project_id,
                        title,
                        patent_id,
                        stamp,
                        stamp,
                        str(uploaded.path.relative_to(self.store.root)),
                        uploaded.sha256,
                        uploaded.sha256,
                        uploaded.page_count,
                        encode(snapshot),
                    ),
                )
        except BaseException:
            uploaded.path.unlink(missing_ok=True)
            raise
        return self.project(project_id)

    def attach_pdf(self, project_id: str, uploaded: UploadedPDF) -> Project:
        try:
            with self.store.connect(write=True) as connection:
                project = connection.execute(
                    "SELECT * FROM projects WHERE id=?", (project_id,)
                ).fetchone()
                if project is None:
                    raise WebError(404, "project_not_found", "Project does not exist.")
                if project["pdf_rel"] or not project["import_key"]:
                    raise WebError(
                        409,
                        "pdf_already_attached",
                        "Only an imported project without an original PDF can receive this attachment.",
                    )
                if (
                    not project["expected_sha256"]
                    or uploaded.sha256 != project["expected_sha256"]
                ):
                    raise WebError(
                        409,
                        "source_mismatch",
                        "Uploaded PDF does not match the imported run's source fingerprint.",
                    )
                if (
                    project["page_count"]
                    and uploaded.page_count != project["page_count"]
                ):
                    raise WebError(
                        409,
                        "source_mismatch",
                        "Uploaded PDF page count does not match the imported run.",
                    )
                connection.execute(
                    "UPDATE projects SET pdf_rel=?,sha256=?,page_count=?,updated_at=? WHERE id=?",
                    (
                        str(uploaded.path.relative_to(self.store.root)),
                        uploaded.sha256,
                        uploaded.page_count,
                        now(),
                        project_id,
                    ),
                )
        except BaseException:
            uploaded.path.unlink(missing_ok=True)
            raise
        self.refresh(project_id)
        return self.project(project_id)

    def import_run(
        self,
        run_dir: str | Path,
        *,
        title: str | None = None,
        pdf_path: str | Path | None = None,
    ) -> Project:
        root = Path(run_dir).expanduser()
        view = ArtifactView.read(root)
        if not any(value is not None for value in view.payloads.values()):
            raise WebError(
                422,
                "empty_run",
                "Directory contains no supported extraction artifacts.",
            )
        import_key = str(root.resolve())
        title = self._title(title or root.name)
        metadata = (view.payloads.get("activity") or {}).get("metadata", {})
        summary = view.payloads.get("summary") or {}
        patent_id = summary.get("patent_id") or metadata.get("patent_id") or root.name
        if not isinstance(patent_id, str) or len(patent_id) > 200:
            raise WebError(422, "invalid_artifact", "Run patent identifier is invalid.")
        with self.store.connect() as connection:
            existing = connection.execute(
                "SELECT * FROM projects WHERE import_key=?", (import_key,)
            ).fetchone()
        project_id = existing["id"] if existing else uuid.uuid4().hex
        attached_sha = existing["sha256"] if existing else None
        if attached_sha and attached_sha != view.expected_sha256:
            raise WebError(
                409,
                "source_mismatch",
                "Imported artifact fingerprint no longer matches the attached original.",
            )
        uploaded = (
            copy_original(pdf_path, self.store.root / "uploads")
            if pdf_path is not None
            else None
        )
        try:
            if uploaded and (
                not view.expected_sha256
                or uploaded.sha256 != view.expected_sha256
                or (view.page_count and uploaded.page_count != view.page_count)
            ):
                raise WebError(
                    409,
                    "source_mismatch",
                    "Original PDF does not match the imported run's source fingerprint.",
                )
            snapshot, compounds = view.snapshot(
                project_id, pdf_sha256=uploaded.sha256 if uploaded else attached_sha
            )
            with self.store.connect(write=True) as connection:
                if (
                    not existing
                    and connection.execute("SELECT COUNT(*) FROM projects").fetchone()[
                        0
                    ]
                    >= 200
                ):
                    raise WebError(
                        413, "project_limit", "Workspace has reached its project limit."
                    )
                if not existing:
                    stamp = now()
                    connection.execute(
                        "INSERT INTO projects(id,title,patent_id,created_at,updated_at,expected_sha256,page_count,historical,run_root,import_key) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (
                            project_id,
                            title,
                            patent_id,
                            stamp,
                            stamp,
                            view.expected_sha256,
                            view.page_count,
                            1,
                            import_key,
                            import_key,
                        ),
                    )
                if uploaded and not attached_sha:
                    connection.execute(
                        "UPDATE projects SET pdf_rel=?,sha256=?,page_count=? WHERE id=?",
                        (
                            str(uploaded.path.relative_to(self.store.root)),
                            uploaded.sha256,
                            uploaded.page_count,
                            project_id,
                        ),
                    )
                connection.execute(
                    "DELETE FROM compounds WHERE project_id=?", (project_id,)
                )
                connection.executemany(
                    "INSERT INTO compounds VALUES(?,?,?,?,?,?)",
                    [
                        (
                            project_id,
                            c["dto"]["id"],
                            i,
                            encode(c["dto"]),
                            c["image_path"],
                            c["geometry_space"],
                        )
                        for i, c in enumerate(compounds)
                    ],
                )
                connection.execute(
                    "UPDATE projects SET snapshot=?,historical=?,updated_at=? WHERE id=?",
                    (
                        encode(snapshot),
                        int(snapshot["is_historical"]),
                        now(),
                        project_id,
                    ),
                )
        except BaseException:
            if uploaded:
                uploaded.path.unlink(missing_ok=True)
            raise
        if uploaded and attached_sha:
            uploaded.path.unlink(missing_ok=True)  # The new duplicate copy only.
        return self.project(project_id)

    def refresh(self, project_id: str, *, view: ArtifactView | None = None) -> None:
        project = self.store.project(project_id)
        if not project["run_root"]:
            return
        view = view or ArtifactView.read(Path(project["run_root"]))
        snapshot, compounds = view.snapshot(project_id, pdf_sha256=project["sha256"])
        self.store.snapshot(project_id, snapshot, compounds)

    def job(self, job_id: str) -> Job:
        row = self.store.job(job_id)
        spec = json.loads(row["spec"])
        output = Path(spec["output_dir"])
        project = self.store.project(row["project_id"])
        error = Error.model_validate_json(row["error"]) if row["error"] else None
        resumable = (
            row["status"] in {"failed", "cancelled", "interrupted"}
            and not row["identity"]
            and bool(project["pdf_rel"])
            and project["sha256"] == spec["sha256"]
            and spec.get("runtime_identity") == runtime_identity()
            and output.is_relative_to(self.store.root / "runs")
        )
        return Job(
            id=row["id"],
            project_id=row["project_id"],
            status=row["status"],
            created_at=row["created_at"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            error=error,
            stages=read_stages(
                output
                if output.resolve().is_relative_to(
                    self.store.root / "runs" / row["project_id"]
                )
                else None
            ),
            can_resume=resumable,
            include_intermediates=spec.get("include_intermediates", False),
            force=spec.get("force", False),
            task_note=spec.get("task_note", ""),
        )

    def project(self, project_id: str) -> Project:
        row = self.store.project(project_id)
        snapshot = json.loads(row["snapshot"])
        with self.store.connect() as connection:
            latest = connection.execute(
                "SELECT id FROM jobs WHERE project_id=? ORDER BY created_at DESC,rowid DESC LIMIT 1",
                (project_id,),
            ).fetchone()
        last_job = self.job(latest["id"]) if latest else None
        acceptance = Acceptance.model_validate(
            snapshot.get("acceptance", {"state": "historical"})
        )
        if (
            last_job
            and last_job.status != "complete"
            and acceptance.state == "accepted"
        ):
            acceptance = Acceptance(
                state="failed",
                errors=["The latest job has not completed successfully."],
            )
        return Project(
            id=row["id"],
            title=row["title"],
            patent_id=row["patent_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            pdf=PDFInfo(
                available=bool(row["pdf_rel"]),
                page_count=row["page_count"],
                sha256=row["sha256"] or row["expected_sha256"],
            ),
            is_historical=bool(row["historical"]),
            summary=Summary.model_validate(snapshot.get("summary", {})),
            acceptance=acceptance,
            last_job=last_job,
        )

    def project_ids(self) -> list[str]:
        with self.store.connect() as connection:
            return [
                r[0]
                for r in connection.execute(
                    "SELECT id FROM projects ORDER BY created_at DESC LIMIT 200"
                )
            ]

    def job_ids(self, project_id: str | None = None) -> list[str]:
        if project_id:
            self.store.project(project_id)
        with self.store.connect() as connection:
            return [
                r[0]
                for r in connection.execute(
                    "SELECT id FROM jobs WHERE (? IS NULL OR project_id=?) ORDER BY created_at DESC LIMIT 500",
                    (project_id, project_id),
                )
            ]

    def result_rows(self, project_id: str) -> list[dict[str, Any]]:
        return self.result_queries.rows(project_id)

    def compounds(self, project_id: str, **filters: str) -> list[Compound]:
        return self.result_queries.compounds(project_id, **filters)

    def results(
        self, project_id: str, *, page: int = 1, page_size: int = 10, **filters: str
    ) -> Results:
        return self.result_queries.results(
            project_id, page=page, page_size=page_size, **filters
        )


def import_run(
    state_root: str | Path,
    run_dir: str | Path,
    *,
    title: str | None = None,
    pdf_path: str | Path | None = None,
) -> Project:
    """CLI-only operator-approved, read-only run import. Never imports arbitrary HTTP paths."""
    from .owner import WorkspaceOwner

    service = WorkspaceService(state_root)
    owner = WorkspaceOwner(service.store.root)
    owner.acquire()
    try:
        return service.import_run(run_dir, title=title, pdf_path=pdf_path)
    finally:
        owner.release()
