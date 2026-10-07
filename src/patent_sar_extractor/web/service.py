"""Workspace use cases shared by HTTP and controller-owned CLI commands."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from patent_sar_extractor import contracts as core

from .admet_history import read_admet_stage
from .artifacts import RAW_PROJECTION_LAYOUT, ArtifactView
from .attempts import AttemptHistory, spec_record
from .correction_models import CorrectionDocument, CorrectionRequest
from .corrections import Corrections, CorrectionSaved
from .descriptor_storage import DescriptorStore
from .errors import WebError
from .files import SafeFiles
from .lead_storage import LeadStore
from .leads import LeadService
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
from .prediction_storage import PredictionStore
from .processes import runtime_identity
from .result_queries import ResultQueries
from .source_epoch import EPOCH_MARKER
from .storage import Store, encode, now
from .table_filter_choices import ColumnFilterValues
from .task_inputs import patent_identifier


class WorkspaceService:
    def __init__(
        self,
        state_root: str | Path,
        *,
        correction_on_save: CorrectionSaved | None = None,
    ) -> None:
        self.store = Store(state_root)
        self.attempts = AttemptHistory(self.store)
        self.corrections = Corrections(
            self.store, self._current_project, on_save=correction_on_save
        )
        self.predictions = PredictionStore(self.store)
        self.descriptors = DescriptorStore(self.store)
        self.lead_store = LeadStore(self.store)
        self.result_queries = ResultQueries(
            self.store,
            self._current_project,
            self.predictions,
            self.descriptors,
            self.lead_store,
        )
        self.leads = LeadService(self)
        self.corrections.after_save = self.leads.after_correction

    def _current_project(self, project_id: str) -> dict[str, Any]:
        row = self.store.project(project_id)
        snapshot = json.loads(row["snapshot"])
        if row["run_root"] and (
            snapshot.get("read_model_identity") != runtime_identity()
            or "first_structure_page" not in snapshot
            or snapshot.get("raw_projection_layout") != RAW_PROJECTION_LAYOUT
        ):
            # Projection data is rebuildable. Old cached acceptance must not
            # become current authority after a rules/software upgrade.
            self.refresh(project_id)
            row = self.store.project(project_id)
        elif row["run_root"] and (
            type(snapshot.get(EPOCH_MARKER)) is not int
            or snapshot[EPOCH_MARKER] != core.STEREO_EVIDENCE_VERSION
        ):
            self._refresh_source_epoch(row, snapshot)
            row = self.store.project(project_id)
        return row

    def _refresh_source_epoch(
        self, project: dict[str, Any], snapshot: dict[str, Any]
    ) -> None:
        """Recheck cached acceptance without changing raw rows/manual audit basis."""
        from .acceptance import authority
        from .stages import completed_stage_payloads

        root = Path(project["run_root"])
        view = ArtifactView.read(root)
        accepted, _ = authority(
            completed_stage_payloads(view.payloads),
            pdf_verified=bool(
                project["sha256"] and project["sha256"] == view.expected_sha256
            ),
            marker=SafeFiles(root).json("STRICT_ACCEPTANCE_FAILED.json"),
        )
        updated = {
            **snapshot,
            "acceptance": accepted.model_dump(),
            EPOCH_MARKER: core.STEREO_EVIDENCE_VERSION,
        }
        # No raw DTO, projection ID, correction, history or saved observation is
        # rewritten. A concurrent new attempt cannot acquire this old read view.
        with self.store.connect(write=True) as connection:
            changed = connection.execute(
                "UPDATE projects SET snapshot=? WHERE id=? AND run_root=? AND sha256 IS ? AND snapshot=?",
                (
                    encode(updated),
                    project["id"],
                    project["run_root"],
                    project["sha256"],
                    project["snapshot"],
                ),
            ).rowcount
            if changed != 1:
                raise WebError(
                    409,
                    "projection_changed",
                    "Source view changed during epoch revalidation; retry the read.",
                )

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
                        self.store.locations.pdf_record(uploaded.path),
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
                        self.store.locations.pdf_record(uploaded.path),
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
            copy_original(pdf_path, self.store.locations.upload_root())
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
            snapshot["correction_projection_id"] = uuid.uuid4().hex
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
                            self.store.locations.pdf_record(uploaded.path),
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
        if view.root.resolve() != Path(project["run_root"]).resolve():
            return  # A supplied old view must never be rebound to a new attempt.
        snapshot, compounds = view.snapshot(project_id, pdf_sha256=project["sha256"])
        snapshot["correction_projection_id"] = uuid.uuid4().hex
        snapshot[EPOCH_MARKER] = core.STEREO_EVIDENCE_VERSION
        self.store.snapshot(
            project_id,
            snapshot,
            compounds,
            expected_run_root=project["run_root"],
            expected_sha256=project["sha256"],
        )

    def job(self, job_id: str) -> Job:
        row = self.store.job(job_id)
        try:
            spec = spec_record(row["spec"])
        except WebError:
            spec = {}
        output = self.attempts.output(row)
        project = self.store.project(row["project_id"])
        error = Error.model_validate_json(row["error"]) if row["error"] else None
        resumable = (
            row["status"] in {"failed", "cancelled", "interrupted"}
            and not row["identity"]
            and bool(project["pdf_rel"])
            and project["sha256"] == spec.get("sha256")
            and spec.get("runtime_identity") == runtime_identity()
            and output is not None
            and self.attempts.unique(row)
        )
        history = self.attempts.read(row) if spec else None
        admet_stage, _ = (
            read_admet_stage(row, output, state_root=self.store.root)
            if spec.get("include_admet")
            else (None, False)
        )
        admet_only = spec.get("admet_only", False)
        if (
            admet_stage is not None
            and admet_stage.status == "running"
            and row["status"] == "running"
            and output
        ):
            from .files import SafeFiles
            from .resource_progress import read_wait

            admet_stage.resource_wait = read_wait(SafeFiles(output), "admet")
        return Job(
            id=row["id"],
            project_id=row["project_id"],
            status=row["status"],
            created_at=row["created_at"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            error=error,
            stages=[] if admet_only else (history.stages if history else []),
            can_resume=resumable,
            history_available=(admet_stage is not None)
            if admet_only
            else (history.available if history else False),
            include_intermediates=spec.get("include_intermediates", False),
            force=spec.get("force", False),
            task_note=spec.get("task_note", ""),
            include_admet=spec.get("include_admet", False),
            admet_only=admet_only,
            admet_stage=admet_stage,
            stage_order=[]
            if admet_only
            else (history.stage_order if history else None),
        )

    def project(self, project_id: str) -> Project:
        row = self._current_project(project_id)
        snapshot = json.loads(row["snapshot"])
        with self.store.connect() as connection:
            latest = connection.execute(
                "SELECT * FROM jobs WHERE project_id=? ORDER BY created_at DESC,rowid DESC LIMIT 1",
                (project_id,),
            ).fetchone()
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
        last_job = self.job(latest["id"]) if latest else None
        acceptance = Acceptance.model_validate(
            snapshot.get("acceptance", {"state": "historical"})
        )
        core_completed = False
        if latest and last_job and last_job.include_admet and not last_job.admet_only:
            _, core_completed = read_admet_stage(
                dict(latest),
                self.attempts.output(dict(latest)),
                state_root=self.store.root,
            )
        if (
            last_job
            and not last_job.admet_only
            and not core_completed
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
            summary=Summary.model_validate(
                {
                    **snapshot.get("summary", {}),
                    "manually_reviewed": review_counts["decided"],
                    "manual_review_pending": review_counts["total"]
                    - review_counts["decided"],
                }
            ),
            acceptance=acceptance,
            last_job=last_job,
            first_structure_page=first_structure,
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

    def get_correction(self, project_id: str, compound_id: str) -> CorrectionDocument:
        return self.corrections.get(project_id, compound_id)

    def put_correction(
        self, project_id: str, compound_id: str, request: CorrectionRequest
    ) -> CorrectionDocument:
        return self.corrections.put(project_id, compound_id, request)

    def effective_compound(self, project_id: str, compound_id: str) -> Compound:
        return self.corrections.compound(project_id, compound_id)

    def effective_compounds(self, project_id: str) -> list[Compound]:
        return self.result_queries.effective_compounds(project_id)

    def compounds(self, project_id: str, **filters: str) -> list[Compound]:
        return self.result_queries.compounds(project_id, **filters)

    def results(
        self, project_id: str, *, page: int = 1, page_size: int = 10, **filters: str
    ) -> Results:
        return self.result_queries.results(
            project_id, page=page, page_size=page_size, **filters
        )

    def filter_values(
        self,
        project_id: str,
        *,
        column: str,
        search: str = "",
        page: int = 1,
        page_size: int = 200,
        **filters: str,
    ) -> ColumnFilterValues:
        return self.result_queries.filter_values(
            project_id,
            column=column,
            search=search,
            page=page,
            page_size=page_size,
            **filters,
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
