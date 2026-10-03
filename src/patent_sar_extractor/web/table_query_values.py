"""Single column accessor shared by full-project workbook filters and ordering."""

from __future__ import annotations

from typing import Any

from .activity_columns import activity_column_id, activity_context
from .models import Compound


def column_values(row: Compound, column: str) -> list[Any]:
    if column == "compound":
        return [row.display_id]
    if column == "structure":
        return [row.structure_image_url] if row.structure_image_url else []
    if column == "source":
        return [row.source.page] if row.source.page is not None else []
    if column == "edit":
        return [
            "待重核"
            if row.correction and row.correction.stale
            else "已修正"
            if row.correction and row.correction.has_changes
            else "原始值"
        ]
    if column.startswith("activity:"):
        key = column.removeprefix("activity:")
        return [
            activity.value
            for activity in row.activities
            if activity_column_id(activity_context(activity)) == key
            and activity.value is not None
        ]
    if column.startswith("property:"):
        if row.admet is None or row.admet.status != "complete":
            return []
        return [
            metric.value
            for metric in row.admet.properties
            if metric.key == column.removeprefix("property:")
        ]
    return []
