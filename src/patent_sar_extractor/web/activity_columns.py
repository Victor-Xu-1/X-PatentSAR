"""Bounded presentation columns from exact observed activity contexts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable

from .activity_ranking import RankBudget, RankDistribution
from .errors import WebError
from .models import Activity, ActivityColumn

ActivityContext = tuple[str, str | None, str | None, str | None]
MAX_ACTIVITY_COLUMNS = 1000


def activity_context(activity: Activity) -> ActivityContext:
    return activity.name, activity.unit, activity.target, activity.assay


def activity_column_id(context: ActivityContext) -> str:
    """Match a compact JSON array without normalizing any source field."""
    try:
        serialized = json.dumps(
            context, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ).encode("utf-8")
    except UnicodeEncodeError as exc:
        raise WebError(
            422, "invalid_activity_column", "Activity context is not valid UTF-8."
        ) from exc
    return hashlib.sha256(serialized).hexdigest()


class ActivityColumnCatalog:
    """Collect once during the existing effective-row scan, before filtering."""

    def __init__(self) -> None:
        self._columns: dict[ActivityContext, ActivityColumn] = {}
        self._rank_budget = RankBudget()
        self._ranks: dict[ActivityContext, RankDistribution] = {}

    def observe(self, activities: Iterable[Activity], *, compound_id: str) -> None:
        for activity in activities:
            context = activity_context(activity)
            if context in self._ranks:
                self._ranks[context].observe(activity.value, compound_id)
            if context in self._columns:
                continue
            if len(self._columns) >= MAX_ACTIVITY_COLUMNS:
                raise WebError(
                    422,
                    "activity_column_limit",
                    "Activity columns exceed the limit of 1000 distinct contexts.",
                )
            name, unit, target, assay = context
            self._columns[context] = ActivityColumn(
                id=activity_column_id(context),
                name=name,
                unit=unit,
                target=target,
                assay=assay,
            )
            distribution = self._ranks[context] = RankDistribution(self._rank_budget)
            distribution.observe(activity.value, compound_id)

    def columns(self) -> list[ActivityColumn]:
        contexts = sorted(
            self._columns,
            key=lambda context: tuple(
                (value is not None, value or "") for value in context
            ),
        )
        return [
            self._columns[context].model_copy(
                update={
                    "strength_scale": self._ranks[context].profile(
                        context[0], context[1], context[3]
                    ),
                }
            )
            for context in contexts
        ]
