"""Read-only filtered results and bounded PDF-coordinate presentation."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .activity_columns import ActivityColumnCatalog
from .correction_storage import (
    CORRECTION_COLUMNS,
    CORRECTION_JOIN,
    correction_source_fingerprint,
    joined_correction,
)
from .corrections import apply_correction
from .errors import WebError
from .models import ActivityColumn, Compound, Results, Review
from .molecule_drawing import drawing_url
from .pdf import open_pdf, rendered_box
from .prediction_storage import PredictionStore
from .storage import Store


class ResultQueries:
    def __init__(
        self,
        store: Store,
        current_project: Callable[[str], dict[str, Any]],
        predictions: PredictionStore | None = None,
    ) -> None:
        self.store = store
        self.current_project = current_project
        self.predictions = predictions

    def _rows_and_project(
        self, project_id: str
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        self.current_project(project_id)
        with self.store.connect() as connection:
            connection.execute("BEGIN")
            project = dict(
                connection.execute(
                    "SELECT * FROM projects WHERE id=?", (project_id,)
                ).fetchone()
            )
            rows = [
                dict(row)
                for row in connection.execute(
                    "SELECT c.*,r.decision,r.note,r.revision,r.updated_at AS review_updated_at "
                    + CORRECTION_COLUMNS
                    + "FROM compounds c "
                    "LEFT JOIN reviews r ON c.project_id=r.project_id AND c.id=r.compound_id "
                    + CORRECTION_JOIN
                    + "WHERE c.project_id=? ORDER BY c.ordinal LIMIT 25000",
                    (project_id,),
                )
            ]
        return rows, project

    def rows(self, project_id: str) -> list[dict[str, Any]]:
        rows, _ = self._rows_and_project(project_id)
        return rows

    def _filtered_compounds(
        self,
        project_id: str,
        *,
        q: str = "",
        confidence: str = "",
        review: str = "",
        target: str = "",
    ) -> tuple[
        list[Compound],
        dict[str, str],
        list[str],
        list[str],
        tuple[dict[str, Any], dict[str, dict[str, Any]]],
        list[ActivityColumn],
    ]:
        if len(q) > 500 or len(target) > 300:
            raise WebError(422, "filter_limit", "Search filter is too long.")
        if confidence not in {
            "",
            "high",
            "medium",
            "review",
            "unknown",
        } or review not in {"", "approved", "rejected", "needs_review", "unreviewed"}:
            raise WebError(422, "invalid_filter", "Result filter is not supported.")
        output = []
        source_spaces: dict[str, str] = {}
        metrics: set[str] = set()
        targets: set[str] = set()
        activity_columns = ActivityColumnCatalog()
        rows, project = self._rows_and_project(project_id)
        for row in rows:
            dto = apply_correction(
                project,
                row,
                joined_correction(row),
                Compound.model_validate_json(row["payload"]),
            )
            activity_columns.observe(dto.activities)
            metrics.update(a.name for a in dto.activities)
            targets.update(a.target for a in dto.activities if a.target)
            if len(metrics) > 1000 or len(targets) > 1000:
                raise WebError(
                    422,
                    "result_vocabulary_limit",
                    "Result metrics or targets exceed their limit.",
                )
            if dto.smiles and dto.redraw_image_url is None:
                # Rendering is derived presentation; old recognition metadata
                # remains unknown instead of being promoted to fresh validation.
                dto.redraw_image_url = drawing_url(project_id, dto.id, dto.smiles)
                if dto.recognition.status == "not_run":
                    dto.recognition.status = "unavailable"
            if row["decision"]:
                dto.review = Review(
                    decision=row["decision"],
                    note=row["note"],
                    revision=row["revision"],
                    updated_at=row["review_updated_at"],
                )
            haystack = " ".join(
                [
                    dto.id,
                    dto.display_id,
                    dto.smiles or "",
                    *(a.name for a in dto.activities),
                    *(a.target or "" for a in dto.activities),
                    *(a.assay or "" for a in dto.activities),
                    *(a.unit or "" for a in dto.activities),
                    *(
                        str(a.value) if a.value is not None else ""
                        for a in dto.activities
                    ),
                ]
            )
            if q and q.casefold() not in haystack.casefold():
                continue
            if confidence and dto.confidence.level != confidence:
                continue
            if review == "unreviewed" and dto.review is not None:
                continue
            if (
                review
                and review != "unreviewed"
                and (dto.review is None or dto.review.decision != review)
            ):
                continue
            if target and not any(a.target == target for a in dto.activities):
                continue
            output.append(dto)
            source_spaces[dto.id] = row["geometry_space"]
        return (
            output,
            source_spaces,
            sorted(metrics),
            sorted(targets),
            (project, {row["id"]: row for row in rows}),
            activity_columns.columns(),
        )

    def _predictions(
        self,
        project_id: str,
        items: list[Compound],
        context: tuple[dict[str, Any], dict[str, dict[str, Any]]],
    ) -> list[Compound]:
        if self.predictions is not None and items:
            project, by_id = context
            values = self.predictions.summaries(
                project_id,
                [
                    (
                        item.id,
                        correction_source_fingerprint(project, by_id[item.id]),
                        item.smiles,
                    )
                    for item in items
                ],
            )
            for item in items:
                item.admet = values[item.id]
        return items

    def _normalize_source_boxes(
        self,
        project_id: str,
        items: list[Compound],
        source_spaces: dict[str, str],
        *,
        checked: list[Compound] | None = None,
    ) -> list[Compound]:
        checked = checked if checked is not None else items
        project = self.store.project(project_id)
        if project["pdf_rel"] and checked:
            with open_pdf(self.store.root, project) as document:
                # Preserve global bounds and source-fingerprint validation, but
                # materialize PDF pages only for rows actually returned.
                for dto in checked:
                    if (
                        dto.source.page
                        and dto.source.bbox
                        and dto.source.page > document.page_count
                    ):
                        raise WebError(
                            422,
                            "invalid_geometry",
                            "Compound source page is outside the original PDF.",
                        )
                for dto in items:
                    if dto.source.page and dto.source.bbox:
                        dto.source.bbox = rendered_box(
                            document[dto.source.page - 1],
                            dto.source.bbox,
                            source_spaces[dto.id],
                        )
        return items

    def effective_compounds(self, project_id: str) -> list[Compound]:
        """Corrected molecules for downstream consumers, without opening PDF pages."""
        items, _, _, _, _, _ = self._filtered_compounds(project_id)
        return items

    def compounds(
        self,
        project_id: str,
        *,
        q: str = "",
        confidence: str = "",
        review: str = "",
        target: str = "",
    ) -> list[Compound]:
        items, source_spaces, _, _, context, _ = self._filtered_compounds(
            project_id, q=q, confidence=confidence, review=review, target=target
        )
        return self._predictions(
            project_id,
            self._normalize_source_boxes(project_id, items, source_spaces),
            context,
        )

    def results(
        self, project_id: str, *, page: int = 1, page_size: int = 10, **filters: str
    ) -> Results:
        if not 1 <= page <= 25000 or not 1 <= page_size <= 100:
            raise WebError(
                422,
                "pagination",
                "Page must be positive and page_size must be at most 100.",
            )
        compounds, source_spaces, metrics, targets, context, activity_columns = (
            self._filtered_compounds(project_id, **filters)
        )
        offset = (page - 1) * page_size
        return Results(
            items=self._predictions(
                project_id,
                self._normalize_source_boxes(
                    project_id,
                    compounds[offset : offset + page_size],
                    source_spaces,
                    checked=compounds,
                ),
                context,
            ),
            total=len(compounds),
            page=page,
            page_size=page_size,
            metrics=metrics,
            targets=targets,
            activity_columns=activity_columns,
        )
