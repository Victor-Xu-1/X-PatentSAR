"""Bounded cross-dataset history over the sole SAR store and job-view authority."""

import json
from typing import TYPE_CHECKING

from pydantic import Field

from ..dto import DTO
from ..errors import WebError
from .models import Dataset, SARJob

if TYPE_CHECKING:
    from .queue import SARQueue


class HistoryItem(DTO):
    job: SARJob
    dataset_title: str
    title: str | None


class HistoryPage(DTO):
    items: list[HistoryItem] = Field(max_length=100)
    total: int = Field(ge=0)
    page: int = Field(ge=1, le=2048)
    page_size: int = Field(ge=1, le=100)
    active_count: int = Field(ge=0)


def history(
    queue: "SARQueue",
    *,
    page: int,
    page_size: int,
    dataset_id: str | None,
    status: str | None,
) -> HistoryPage:
    """No task submission, full-report loading, scientific inference or second history."""
    clauses, parameters = ["j.deleted=0", "d.deleted=0"], []
    for column, value in (("j.dataset_id", dataset_id), ("j.status", status)):
        if value is not None:
            clauses.append(column + "=?")
            parameters.append(value)
    query = " FROM jobs j JOIN datasets d ON d.id=j.dataset_id WHERE " + " AND ".join(
        clauses
    )
    with queue.jobs.store.connect() as connection:
        counts = connection.execute(
            "SELECT COUNT(*), COALESCE(SUM(j.status IN ('queued','running')),0)"
            + query,
            parameters,
        ).fetchone()
        records = connection.execute(
            "SELECT j.id,j.spec,d.metadata"
            + query
            + " ORDER BY json_extract(j.payload,'$.created_at') DESC,j.rowid DESC LIMIT ? OFFSET ?",
            [*parameters, page_size, (page - 1) * page_size],
        ).fetchall()
    items = []
    for record in records:
        dataset = Dataset.model_validate_json(record["metadata"])
        job = queue.view(record["id"])
        if job.id != record["id"] or job.dataset_id != dataset.id:
            raise WebError(
                409,
                "sar_history_changed",
                "SAR history identity changed; refresh the task list.",
            )
        request = json.loads(record["spec"])["request"]
        title = (
            request.get("title")
            if job.kind == "study"
            else next(
                (
                    metric.name
                    for metric in dataset.metrics
                    if metric.id == job.metric_id
                ),
                None,
            )
        )
        items.append(HistoryItem(job=job, dataset_title=dataset.title, title=title))
    return HistoryPage(
        items=items,
        total=counts[0],
        active_count=counts[1],
        page=page,
        page_size=page_size,
    )
