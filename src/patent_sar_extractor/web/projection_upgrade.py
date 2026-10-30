"""A presentation-only rebuild may retain an exactly unchanged correction basis."""

from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

_PRESENTATION = {
    "correction_projection_id",
    "raw_projection_layout",
    "historical_source_review_version",
}


def unchanged_upgrade_identity(
    connection: sqlite3.Connection,
    project_id: str,
    current: str,
    snapshot: dict[str, Any],
    values: list[tuple[Any, ...]],
) -> str | None:
    """Compare inside the publication transaction, never from an earlier read.

    This is only for implicit read-model presentation upgrades. Explicit refresh
    and changed sources still receive a new projection identity. No correction
    row or immutable audit entry is rewritten or automatically rebased.
    """
    previous = json.loads(current)
    if (
        not isinstance(previous, dict)
        or previous.get("is_historical") is not False
        or snapshot.get("is_historical") is not False
        or not isinstance(previous.get("correction_projection_id"), str)
        or re.fullmatch(r"[a-f0-9]{32}", previous["correction_projection_id"]) is None
        or {key: value for key, value in previous.items() if key not in _PRESENTATION}
        != {key: value for key, value in snapshot.items() if key not in _PRESENTATION}
    ):
        return None
    rows = connection.execute(
        "SELECT id,ordinal,payload,image_path,geometry_space "
        "FROM compounds WHERE project_id=? ORDER BY ordinal,id",
        (project_id,),
    ).fetchall()
    expected = sorted(
        (value[1:] for value in values), key=lambda value: (value[1], value[0])
    )
    if len(rows) != len(expected):
        return None
    for row, candidate in zip(rows, expected, strict=True):
        if (row[0], row[1], row[3], row[4]) != (
            candidate[0],
            candidate[1],
            candidate[3],
            candidate[4],
        ) or json.loads(row[2]) != json.loads(candidate[2]):
            return None
    return previous["correction_projection_id"]
