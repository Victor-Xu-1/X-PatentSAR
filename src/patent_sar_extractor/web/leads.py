"""One lightweight tail of the existing research job and audited edit workflow."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

from .activity_columns import ActivityColumnCatalog
from .errors import WebError
from .lead_storage import input_fingerprint

if TYPE_CHECKING:
    from .service import WorkspaceService


class LeadService:
    def __init__(self, service: WorkspaceService) -> None:
        self.service = service

    def refresh(
        self,
        project_id: str,
        *,
        job_id: str | None = None,
        cancel: Callable[[], bool] | None = None,
    ) -> dict:
        # Model inference/its lease has ended. Fingerprints and selection are
        # computed once in the owned worker, never during a GET/filter/export.
        from .lead_scoring import prioritize_leads

        store = self.service.lead_store
        revision = store.revision(project_id)
        compounds = self.service.result_queries.research_compounds(project_id)
        project = self.service.store.project(project_id)
        fingerprint = input_fingerprint(project, compounds)
        catalog = ActivityColumnCatalog()
        for compound in compounds:
            catalog.observe(compound.activities, compound_id=compound.id)
        try:
            assessments = prioritize_leads(compounds, catalog.columns(), cancel=cancel)
            if cancel and cancel():
                raise WebError(409, "lead_cancelled", "Lead evaluation was cancelled.")
        except WebError as exc:
            # A failed/cancelled computation never retains a current selected
            # packet. The original extraction and observations stay untouched.
            if exc.code != "lead_cancelled":
                store.publish(
                    project_id,
                    fingerprint,
                    revision,
                    {},
                    job_id=job_id,
                    failure=exc.code,
                )
            raise
        return store.publish(
            project_id, fingerprint, revision, assessments, job_id=job_id
        )

    def after_correction(self, project_id: str) -> None:
        with self.service.store.connect() as connection:
            active = connection.execute(
                "SELECT 1 FROM jobs WHERE project_id=? AND status IN ('queued','running')",
                (project_id,),
            ).fetchone()
        # A graph edit already queued its one normal property worker. Do not
        # compete with that owner or pretend old ADMET matches the new graph.
        if active:
            return
        try:
            if not self.service.lead_store.has_report(project_id):
                return
            self.refresh(project_id)
        except WebError as exc:
            # The correction transaction has committed successfully. Failed or
            # changed-input Lead state is explicit on the next read, not a false
            # "save failed" response encouraging the user to repeat the write.
            logging.getLogger(__name__).warning(
                "Lead recomputation after committed correction failed code=%s", exc.code
            )

    def confirm(self, project_id: str, job_id: str) -> None:
        """Read-only job gate, shared with table currentness; never recompute."""
        report = self.service.lead_store.report(project_id)
        project = self.service.store.project(project_id)
        compounds = self.service.result_queries.research_compounds(project_id)
        if (
            report is None
            or report["status"] != "complete"
            or report["job_id"] != job_id
            or report["input_fingerprint"] != input_fingerprint(project, compounds)
            or set(report["items"]) != {value.id for value in compounds}
        ):
            raise WebError(
                502,
                "lead_incomplete",
                "Project-wide Lead evaluation is missing or stale; task completion was withheld.",
            )
