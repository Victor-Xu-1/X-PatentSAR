"""Read-only filtered results and bounded PDF-coordinate presentation."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .activity_columns import ActivityColumnCatalog
from .activity_focus import activity_source_keys
from .activity_rank_values import rank_value
from .correction_storage import (
    CORRECTION_COLUMNS,
    CORRECTION_JOIN,
    correction_source_fingerprint,
    joined_correction,
)
from .corrections import apply_correction
from .dto import Error
from .errors import WebError
from .models import ActivityColumn, Compound, Results, Review
from .molecule_drawing import drawing_url
from .pdf import open_pdf, rendered_box
from .prediction_identity import source_stereo_blocked
from .prediction_models import PredictionSummary
from .prediction_storage import PredictionStore
from .recognition_storage import (
    RECOGNITION_COLUMNS,
    RECOGNITION_JOIN,
    apply_recognition,
)
from .storage import Store
from .table_filter_choices import ColumnFilterValues, choice_parameters, filter_choices
from .table_queries import validate_columns, workbook_rows
from .table_query_models import column_filters as parse_column_filters


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
                    + RECOGNITION_COLUMNS
                    + "FROM compounds c "
                    "LEFT JOIN reviews r ON c.project_id=r.project_id AND c.id=r.compound_id "
                    + CORRECTION_JOIN
                    + RECOGNITION_JOIN
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
        column_filters: str = "",
        sort_column: str = "",
        sort_direction: str = "asc",
        sort_band: str = "",
        choice_column: str = "",
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
        # Reject oversized/malformed input before the full effective-row scan.
        criteria = parse_column_filters(column_filters)
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
                apply_recognition(
                    project, row, Compound.model_validate_json(row["payload"])
                ),
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
                dto.redraw_image_url = drawing_url(
                    project_id, dto.id, dto.smiles, dto.structure_molfile
                )
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
        catalog = activity_columns.columns()
        validate_columns(criteria, sort_column, sort_direction, catalog, sort_band)
        if choice_column:
            validate_columns([], choice_column, "asc", catalog)
            criteria = [item for item in criteria if item.column != choice_column]
        context = (project, {row["id"]: row for row in rows})
        if (
            choice_column.startswith("property:")
            or sort_column.startswith("property:")
            or any(item.column.startswith("property:") for item in criteria)
        ):
            output = self._predictions(project_id, output, context)
        output = workbook_rows(
            output, criteria, sort_column, sort_direction, catalog, sort_band
        )
        return (
            output,
            source_spaces,
            sorted(metrics),
            sorted(targets),
            context,
            catalog,
        )

    def _predictions(
        self,
        project_id: str,
        items: list[Compound],
        context: tuple[dict[str, Any], dict[str, dict[str, Any]]],
    ) -> list[Compound]:
        eligible = []
        for item in items:
            if source_stereo_blocked(item):
                item.admet = PredictionSummary(
                    status="unavailable",
                    error=Error(
                        code="admet_stereo_source_unresolved",
                        message="Source stereochemistry requires a validated graph correction before inference.",
                    ),
                )
            elif item.recognition.status == "invalid":
                item.admet = PredictionSummary(
                    status="unavailable",
                    error=Error(
                        code="admet_recognition_rejected",
                        message="Rejected source chemistry requires a validated correction before inference.",
                    ),
                )
            else:
                eligible.append(item)
        if (
            self.predictions is not None
            and eligible
            and any(item.admet is None for item in eligible)
        ):
            project, by_id = context
            values = self.predictions.summaries(
                project_id,
                [
                    (
                        item.id,
                        correction_source_fingerprint(project, by_id[item.id]),
                        item.smiles,
                    )
                    for item in eligible
                ],
                molfiles={item.id: item.structure_molfile for item in eligible},
            )
            for item in eligible:
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
        column_filters: str = "",
        sort_column: str = "",
        sort_direction: str = "asc",
        sort_band: str = "",
    ) -> list[Compound]:
        items, source_spaces, _, _, context, _ = self._filtered_compounds(
            project_id,
            q=q,
            confidence=confidence,
            review=review,
            target=target,
            column_filters=column_filters,
            sort_column=sort_column,
            sort_direction=sort_direction,
            sort_band=sort_band,
        )
        return self._predictions(
            project_id,
            self._normalize_source_boxes(project_id, items, source_spaces),
            context,
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
        choice_parameters(column, search, page, page_size)
        compounds, _, _, _, _, catalog = self._filtered_compounds(
            project_id, choice_column=column, **filters
        )
        return filter_choices(
            compounds, column, catalog, search=search, page=page, page_size=page_size
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
        visible = compounds[offset : offset + page_size]
        for item in visible:
            item.activity_rank_values = [
                parsed[1]
                if (parsed := rank_value(activity.value)) is not None
                else None
                for activity in item.activities
            ]
            item.activity_source_keys = activity_source_keys(
                context[0], context[1][item.id], item.activities
            )
        return Results(
            items=self._predictions(
                project_id,
                self._normalize_source_boxes(
                    project_id,
                    visible,
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
