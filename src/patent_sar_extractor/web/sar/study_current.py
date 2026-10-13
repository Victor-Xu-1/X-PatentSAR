"""Bounded immutable-byte cache for the current source-scope/activity view."""

import hashlib
import json
from functools import lru_cache

from ..errors import WebError
from ..storage import encode
from .study_models import StudyReport
from .study_view import current_records, current_report
from .study_view_models import ActivityBasis


def _derive(
    source: bytes,
    report: bytes,
    pairs: bytes,
    *,
    captured=None,
    records_only=False,
    catalog=False,
):
    project = current_records if records_only else current_report
    return project(
        json.loads(source),
        captured if captured is not None else StudyReport.model_validate_json(report),
        json.loads(pairs),
        **({"catalog": catalog} if not records_only else {}),
    )


_small_view = lru_cache(maxsize=2)(_derive)


def projected(queue, identifier, job, captured, *, records_only=False, catalog=False):
    record = queue.jobs.record(identifier)
    safe = queue.service.assets.job_files(record["root"], identifier)
    source = safe.read("input.json", max_bytes=32 * 1024 * 1024)
    report = safe.read("report.json", max_bytes=32 * 1024 * 1024)
    spec = json.loads(record["spec"])
    if hashlib.sha256(source).hexdigest() != job.input_sha256 or hashlib.sha256(
        report
    ).hexdigest() != spec.get("report_sha256"):
        raise WebError(
            409,
            "sar_input_changed",
            "Current view source differs from the immutable study receipt.",
        )
    with queue.service.store.connect() as connection:
        compact = [
            dict(row)
            for row in connection.execute(
                "SELECT json_extract(payload,'$.region_id') AS region_id, json_extract(payload,'$.molecule_id') AS molecule_id, json_extract(payload,'$.fragment_id') AS fragment_id, json_extract(payload,'$.match_status') AS match_status, json_extract(payload,'$.comparison') AS comparison FROM pairs WHERE job_id=? ORDER BY rowid LIMIT 75001",
                (identifier,),
            )
        ]
    if len(compact) != captured.strict_pair_count or len(compact) > 75000:
        raise WebError(
            409,
            "sar_report_scope",
            "Published comparison coverage differs from the captured study.",
        )
    pair_bytes = encode(compact).encode()
    if len(source) + len(report) + len(pair_bytes) <= 4 * 1024 * 1024:
        current, excluded = _small_view(
            source, report, pair_bytes, records_only=records_only, catalog=catalog
        )
    else:
        # load() already validated this captured model. Both subsequent byte
        # receipts were checked above against the SAME immutable input/report
        # hashes. Reuse it rather than parse a large report a second time; do
        # not retain large packets in a process-global cache.
        current, excluded = _derive(
            source,
            report,
            pair_bytes,
            captured=captured,
            records_only=records_only,
            catalog=catalog,
        )
    basis = ActivityBasis(
        source_input_sha256=job.input_sha256,
        source_report_sha256=spec["report_sha256"],
        retained_records=current.molecule_count,
        excluded_records=excluded,
    )
    return current, basis
