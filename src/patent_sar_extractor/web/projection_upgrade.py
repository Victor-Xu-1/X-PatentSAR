"""A presentation-only rebuild may retain an exactly unchanged correction basis."""

from __future__ import annotations

import json
import re
import sqlite3
from itertools import zip_longest
from typing import Any

_PRESENTATION = {
    "correction_projection_id",
    "raw_projection_layout",
    "historical_source_review_version",
}


def _canonical(value: object) -> str:
    # Python equality conflates True, 1 and 1.0; the source fingerprint does not.
    # Preserve JSON type/value identity while ignoring object-key order only.
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


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
        or _canonical(
            {key: value for key, value in previous.items() if key not in _PRESENTATION}
        )
        != _canonical(
            {key: value for key, value in snapshot.items() if key not in _PRESENTATION}
        )
    ):
        return None
    rows = connection.execute(
        "SELECT id,ordinal,payload,image_path,geometry_space "
        "FROM compounds WHERE project_id=? ORDER BY ordinal,id",
        (project_id,),
    )
    # Publication values already carry their consecutive original ordinals.
    # Stream stored rows instead of copying the complete dataset a second time.
    expected = (value[1:] for value in values)
    for row, candidate in zip_longest(rows, expected):
        if row is None or candidate is None:
            return None
        if (row[0], row[1], row[3], row[4]) != (
            candidate[0],
            candidate[1],
            candidate[3],
            candidate[4],
        ) or _canonical(json.loads(row[2])) != _canonical(json.loads(candidate[2])):
            return None
    return previous["correction_projection_id"]
