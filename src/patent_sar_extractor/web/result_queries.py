"""Read-only filtered results and bounded PDF-coordinate presentation."""

from __future__ import annotations

import json
from typing import Any

from .errors import WebError
from .models import Compound, Results, Review
from .pdf import open_pdf, rendered_box
from .storage import Store


class ResultQueries:
    def __init__(self, store: Store) -> None:
        self.store = store

    def rows(self, project_id: str) -> list[dict[str, Any]]:
        self.store.project(project_id)
        with self.store.connect() as connection:
            return [
                dict(row)
                for row in connection.execute(
                    "SELECT c.*,r.decision,r.note,r.revision,r.updated_at AS review_updated_at FROM compounds c "
                    "LEFT JOIN reviews r ON c.project_id=r.project_id AND c.id=r.compound_id "
                    "WHERE c.project_id=? ORDER BY c.ordinal LIMIT 25000",
                    (project_id,),
                )
            ]

    def _filtered_compounds(
        self,
        project_id: str,
        *,
        q: str = "",
        confidence: str = "",
        review: str = "",
        target: str = "",
    ) -> tuple[list[Compound], dict[str, str]]:
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
        for row in self.rows(project_id):
            dto = Compound.model_validate_json(row["payload"])
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
                    dto.smiles or "",
                    *(a.name for a in dto.activities),
                    *(a.target or "" for a in dto.activities),
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
        return output, source_spaces

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
                    if dto.source.page and dto.source.bbox:
                        if dto.source.page > document.page_count:
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

    def compounds(
        self,
        project_id: str,
        *,
        q: str = "",
        confidence: str = "",
        review: str = "",
        target: str = "",
    ) -> list[Compound]:
        items, source_spaces = self._filtered_compounds(
            project_id, q=q, confidence=confidence, review=review, target=target
        )
        return self._normalize_source_boxes(project_id, items, source_spaces)

    def results(
        self, project_id: str, *, page: int = 1, page_size: int = 10, **filters: str
    ) -> Results:
        if not 1 <= page <= 25000 or not 1 <= page_size <= 100:
            raise WebError(
                422,
                "pagination",
                "Page must be positive and page_size must be at most 100.",
            )
        compounds, source_spaces = self._filtered_compounds(project_id, **filters)
        snapshot = json.loads(self.store.project(project_id)["snapshot"])
        offset = (page - 1) * page_size
        return Results(
            items=self._normalize_source_boxes(
                project_id,
                compounds[offset : offset + page_size],
                source_spaces,
                checked=compounds,
            ),
            total=len(compounds),
            page=page,
            page_size=page_size,
            metrics=snapshot.get("metrics", []),
            targets=snapshot.get("targets", []),
        )
