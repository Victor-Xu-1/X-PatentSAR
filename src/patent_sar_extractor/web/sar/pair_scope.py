"""Apply the same source scope before paging published reference comparisons."""

import json

from ..errors import WebError
from .models import Pair
from .source_scope import source_exclusion


def scoped_pairs(connection, job, page: int, page_size: int):
    records = connection.execute(
        "SELECT p.ordinal, m.label, json_extract(m.payload,'$.source_compound_id') AS source_id, json_extract(m.payload,'$.issues') AS issues, r.label AS reference_label, json_extract(r.payload,'$.source_compound_id') AS reference_source_id, json_extract(r.payload,'$.issues') AS reference_issues FROM pairs p JOIN molecules m ON m.dataset_id=? AND m.id=json_extract(p.payload,'$.molecule_id') JOIN molecules r ON r.dataset_id=m.dataset_id AND r.id=json_extract(p.payload,'$.reference_id') WHERE p.job_id=? ORDER BY p.ordinal LIMIT 75001",
        (job.dataset_id, job.id),
    ).fetchall()
    if len(records) > 75000:
        raise WebError(
            413,
            "sar_result_limit",
            "Comparison records exceed the complete scope limit.",
        )
    ordinals = [
        row["ordinal"]
        for row in records
        if source_exclusion(
            row["label"], row["source_id"], json.loads(row["issues"] or "[]")
        )
        is None
        and source_exclusion(
            row["reference_label"],
            row["reference_source_id"],
            json.loads(row["reference_issues"] or "[]"),
        )
        is None
    ]
    shown = ordinals[(page - 1) * page_size : page * page_size]
    if not shown:
        return [], len(ordinals)
    placeholders = ",".join("?" for _ in shown)
    rows = connection.execute(
        "SELECT payload FROM pairs WHERE job_id=? AND ordinal IN ("
        + placeholders
        + ") ORDER BY ordinal",
        (job.id, *shown),
    )
    return [Pair.model_validate_json(row[0]) for row in rows], len(ordinals)
