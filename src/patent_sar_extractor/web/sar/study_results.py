"""Complete, receipt-bound study reads and whole-dataset filtering/pagination."""

from __future__ import annotations

import json

from ..errors import WebError
from .report_preparation import report_preparation
from .study_models import StudyDrawing, StudyOverview, StudyRows
from .study_row_scope import selected_members
from .study_table import order_rows


class StudyResults:
    def __init__(self, queue):
        self.queue = queue

    def load(self, identifier: str):
        job = self.queue.view(identifier)
        if job.kind != "study" or job.status != "complete":
            raise WebError(
                409, "sar_results_pending", "A complete study report is required."
            )
        saved = self.queue.jobs.record(identifier)
        spec = json.loads(saved["spec"])
        content = self.queue.service.assets.job_files(saved["root"], identifier).read(
            "report.json", max_bytes=32 * 1024 * 1024
        )
        report = report_preparation.read(content, spec.get("report_sha256"))
        if (
            report.input_sha256 != job.input_sha256
            or report.dataset_id != job.dataset_id
        ):
            raise WebError(
                409,
                "sar_report_changed",
                "Study report identity differs from the task.",
            )
        return job, report

    def overview(self, identifier: str) -> StudyOverview:
        from .study_view_models import CurrentStudyOverview

        job, report, basis = self.current(identifier)
        return CurrentStudyOverview(
            job=job, report=report.model_copy(update={"rows": []}), activity_basis=basis
        )

    def catalog(self, identifier: str, *, compact: bool = False):
        from .study_catalog_models import StudyCatalog

        job, report, basis = self.current(identifier, catalog=True)
        result = StudyCatalog(
            job=job, report=report.model_copy(update={"rows": []}), activity_basis=basis
        )
        if compact:
            from .study_catalog_wire import pooled_catalog

            return pooled_catalog(result)
        return result

    def region(self, identifier: str, region_id: str):
        from .study_catalog_models import StudyRegionDetail

        if not region_id or len(region_id) > 200:
            raise WebError(422, "sar_region", "Choose a retained region.")
        job, report, basis = self.current(identifier)
        region = next(
            (item for item in report.regions if item.region.id == region_id), None
        )
        if region is None:
            raise WebError(404, "sar_region", "Region is not part of this study.")
        return StudyRegionDetail(job=job, region=region, activity_basis=basis)

    def current(self, identifier: str, *, records_only=False, catalog=False):
        from .study_current import projected

        job, captured = self.load(identifier)
        report, basis = projected(
            self.queue,
            identifier,
            job,
            captured,
            records_only=records_only,
            catalog=catalog,
        )
        return job, report, basis

    def rows(
        self,
        identifier: str,
        page: int = 1,
        page_size: int = 50,
        query: str = "",
        scope: str = "all",
        scaffold_id: str = "",
        region_id: str = "",
        fragment_id: str = "",
        sort_by: str = "label",
        sort_direction: str = "asc",
        reference_id: str = "",
    ) -> StudyRows:
        if (
            not 1 <= page <= 25000
            or not 1 <= page_size <= 200
            or len(query) > 200
            or scope not in {"all", "strong", "leads", "changes", "strong_changes"}
            or (
                scope in {"changes", "strong_changes"}
                and not (region_id or reference_id)
            )
            or any(
                len(value) > 200
                for value in (scaffold_id, region_id, fragment_id, reference_id)
            )
        ):
            raise WebError(422, "sar_page", "Study filter/page exceeds its bound.")
        job, report, _ = self.current(identifier, records_only=True)
        query_ids = None
        if query:
            pattern = (
                "%"
                + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                + "%"
            )
            with self.queue.service.store.connect() as connection:
                query_ids = {
                    row[0]
                    for row in connection.execute(
                        "SELECT id FROM molecules WHERE dataset_id=? AND (label LIKE ? ESCAPE '\\' OR json_extract(payload,'$.smiles') LIKE ? ESCAPE '\\')",
                        (job.dataset_id, pattern, pattern),
                    )
                }
        allowed = selected_members(
            report,
            scope=scope,
            scaffold_id=scaffold_id,
            region_id=region_id,
            fragment_id=fragment_id,
            reference_id=reference_id,
        )
        rows = [
            row
            for row in report.rows
            if (allowed is None or row.molecule_id in allowed)
            and (scope not in {"strong", "strong_changes"} or row.strong)
            and (scope != "leads" or row.candidate_status == "selected")
            and (query_ids is None or row.molecule_id in query_ids)
        ]
        rows = order_rows(rows, report, sort_by, sort_direction)
        return StudyRows(
            items=rows[(page - 1) * page_size : page * page_size],
            total=len(rows),
            page=page,
            page_size=page_size,
            job=job,
        )

    def drawing(
        self, identifier: str, kind: str, key: str, region_id: str = ""
    ) -> StudyDrawing:
        if len(key) > 200 or len(region_id) > 200:
            raise WebError(
                422, "sar_study_drawing", "Drawing selector exceeds its bound."
            )
        job, report = self.load(identifier)
        from .study_drawings import draw_one

        return draw_one(self.queue, identifier, job, report, kind, key, region_id)

    def drawings(
        self, identifier: str, kind: str, keys: list[str], region_id: str = ""
    ):
        from .study_drawing_models import MAX_DRAWING_BATCH
        from .study_drawings import draw_batch

        if (
            not isinstance(kind, str)
            or kind not in {"molecule", "scaffold", "fragment"}
            or not isinstance(keys, list)
            or not 1 <= len(keys) <= MAX_DRAWING_BATCH
            or any(not isinstance(key, str) or not 1 <= len(key) <= 200 for key in keys)
            or len(set(keys)) != len(keys)
            or not isinstance(region_id, str)
            or len(region_id) > 200
        ):
            raise WebError(
                422, "sar_study_drawing", "Drawing batch exceeds its bounded selection."
            )
        job, report = self.load(identifier)
        return draw_batch(self.queue, identifier, job, report, kind, keys, region_id)
