"""Complete, receipt-bound study reads and whole-dataset filtering/pagination."""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache

from ...core.identifier_order import natural_identifier_key
from ...core.sar.drawing import draw_fragment, draw_structure
from ..errors import WebError
from .models import Pair
from .study_models import StudyDrawing, StudyOverview, StudyReport, StudyRows


@lru_cache(maxsize=2)
def _small_report(content: bytes) -> StudyReport:
    # At most two <=4MiB immutable byte packets are cached. Large reports never
    # stay in the web process cache; every read still checks the exact receipt.
    return StudyReport.model_validate_json(content)


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
        if hashlib.sha256(content).hexdigest() != spec.get("report_sha256"):
            raise WebError(
                409,
                "sar_report_changed",
                "Study report bytes differ from the complete receipt.",
            )
        report = (
            _small_report(content)
            if len(content) <= 4 * 1024 * 1024
            else StudyReport.model_validate_json(content)
        )
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
        job, report = self.load(identifier)
        return StudyOverview(job=job, report=report.model_copy(update={"rows": []}))

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
    ) -> StudyRows:
        if (
            not 1 <= page <= 25000
            or not 1 <= page_size <= 200
            or len(query) > 200
            or scope not in {"all", "strong", "leads"}
        ):
            raise WebError(422, "sar_page", "Study filter/page exceeds its bound.")
        job, report = self.load(identifier)
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
        allowed = None
        if scaffold_id:
            scaffold = next(
                (item for item in report.scaffolds if item.id == scaffold_id), None
            )
            if scaffold is None:
                raise WebError(
                    422, "sar_study_filter", "Scaffold is not in this study."
                )
            allowed = set(scaffold.molecule_ids)
        if fragment_id and not region_id:
            raise WebError(
                422, "sar_study_filter", "Fragment selection requires its exact region."
            )
        if region_id:
            region = next(
                (item for item in report.regions if item.region.id == region_id), None
            )
            if region is None:
                raise WebError(422, "sar_study_filter", "Region is not in this study.")
            fragments = [
                item
                for item in region.fragments
                if not fragment_id or item.id == fragment_id
            ]
            if fragment_id and not fragments:
                raise WebError(
                    422, "sar_study_filter", "Fragment is not in this region."
                )
            members = {mid for fragment in fragments for mid in fragment.molecule_ids}
            allowed = members if allowed is None else allowed & members
        rows = [
            row
            for row in report.rows
            if (allowed is None or row.molecule_id in allowed)
            and (scope != "strong" or row.strong)
            and (scope != "leads" or row.candidate_status == "selected")
            and (query_ids is None or row.molecule_id in query_ids)
        ]
        rows.sort(key=lambda row: (natural_identifier_key(row.label), row.molecule_id))
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
                svg = draw_structure(molecule.molfile, highlighted_atoms=atoms)["svg"]
            elif kind == "scaffold":
                scaffold = next(item for item in report.scaffolds if item.id == key)
                svg = draw_fragment(scaffold.smiles or "")
            elif kind == "fragment":
                region = next(
                    item for item in report.regions if item.region.id == region_id
                )
                fragment = next(item for item in region.fragments if item.id == key)
                svg = draw_fragment(fragment.smiles)
            else:
                raise ValueError("unavailable")
        except (StopIteration, ValueError, RuntimeError) as error:
            raise WebError(
                422,
                "sar_structure_unavailable",
                "Study drawing is unavailable; no placeholder molecule was substituted.",
            ) from error
        return StudyDrawing(id=key, svg=svg)
