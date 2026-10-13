"""Complete, receipt-bound study reads and whole-dataset filtering/pagination."""

from __future__ import annotations

import json

from ...core.sar.drawing import draw_fragment, draw_molecule_preview
from ..errors import WebError
from .models import Pair
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

    def catalog(self, identifier: str):
        from .study_catalog_models import StudyCatalog

        job, report, basis = self.current(identifier, catalog=True)
        return StudyCatalog(
            job=job, report=report.model_copy(update={"rows": []}), activity_basis=basis
        )

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
        try:
            if kind == "molecule":
                molecule = self.queue.service.datasets.molecule(job.dataset_id, key)
                if not molecule.eligible or not molecule.molfile:
                    raise ValueError("unavailable")
                atoms = []
                hydrogen_anchor = None
                if region_id:
                    region = next(
                        (
                            item.region
                            for item in report.regions
                            if item.region.id == region_id
                        ),
                        None,
                    )
                    if region is None:
                        raise ValueError("unavailable")
                    if region.molecule_id == key:
                        atoms = region.atom_indices
                        hydrogen_anchor = region.hydrogen_anchor
                    else:
                        with self.queue.service.store.connect() as connection:
                            saved = connection.execute(
                                "SELECT payload FROM pairs WHERE job_id=? AND json_extract(payload,'$.region_id')=? AND json_extract(payload,'$.molecule_id')=? LIMIT 1",
                                (identifier, region_id, key),
                            ).fetchone()
                        if saved:
                            pair = Pair.model_validate_json(saved[0])
                            if pair.match_status == "matched":
                                atoms = pair.variable_atom_indices
                                hydrogen_anchor = pair.candidate_hydrogen_anchor
                svg = draw_molecule_preview(
                    molecule.molfile,
                    highlighted_atoms=atoms,
                    hydrogen_anchor=hydrogen_anchor,
                )
            elif kind == "scaffold":
                scaffold = next(item for item in report.scaffolds if item.id == key)
                svg = draw_fragment(scaffold.smiles or "")
            elif kind == "fragment":
                region = next(
                    item for item in report.regions if item.region.id == region_id
                )
                fragment = next(item for item in region.fragments if item.id == key)
                svg = draw_fragment(fragment.smiles, graph_smiles=fragment.graph_smiles)
            else:
                raise ValueError("unavailable")
        except (StopIteration, ValueError, RuntimeError) as error:
            raise WebError(
                422,
                "sar_structure_unavailable",
                "Study drawing is unavailable; no placeholder molecule was substituted.",
            ) from error
        return StudyDrawing(id=key, svg=svg)
