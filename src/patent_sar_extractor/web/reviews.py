"""Optimistic review updates and immutable audit revisions, never QA writes."""

from __future__ import annotations

from .errors import WebError
from .models import Review, ReviewRequest
from .storage import Store, now


def put_review(
    store: Store, project_id: str, compound_id: str, request: ReviewRequest
) -> Review:
    with store.connect(write=True) as connection:
        compound = connection.execute(
            "SELECT 1 FROM compounds WHERE project_id=? AND id=?",
            (project_id, compound_id),
        ).fetchone()
        if compound is None:
            raise WebError(
                404,
                "compound_not_found",
                "Compound is not in the activity-led result set.",
            )
        existing = connection.execute(
            "SELECT revision FROM reviews WHERE project_id=? AND compound_id=?",
            (project_id, compound_id),
        ).fetchone()
        revision = existing[0] if existing is not None else 0
        if revision != request.expected_revision:
            raise WebError(
                409, "review_conflict", "Review changed; refresh it before saving."
            )
        result = Review(
            decision=request.decision,
            note=request.note,
            revision=revision + 1,
            updated_at=now(),
        )
        values = (
            project_id,
            compound_id,
            result.decision,
            result.note,
            result.revision,
            result.updated_at,
        )
        connection.execute(
            "INSERT INTO reviews VALUES(?,?,?,?,?,?) ON CONFLICT(project_id,compound_id) DO UPDATE SET "
            "decision=excluded.decision,note=excluded.note,revision=excluded.revision,updated_at=excluded.updated_at",
            values,
        )
        connection.execute(
            "INSERT INTO review_audit(project_id,compound_id,decision,note,revision,updated_at) VALUES(?,?,?,?,?,?)",
            values,
        )
        connection.execute(
            "UPDATE projects SET updated_at=? WHERE id=?",
            (result.updated_at, project_id),
        )
    return result
