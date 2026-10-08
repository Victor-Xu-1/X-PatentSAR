"""Idempotent SAR job lifecycle and complete-result CAS in the sole module database."""

from __future__ import annotations

import json
import sqlite3
import uuid

from ..errors import WebError
from ..storage import encode, now
from .models import Dataset, JobList, Pair, PairPage, SARJob
from .store import SARStore, dataset_row, job_row


class Jobs:
    def __init__(self, store: SARStore):
        self.store = store

    def existing(self, request_id: str, request_sha256: str) -> SARJob | None:
        with self.store.connect() as connection:
            row = connection.execute(
                "SELECT * FROM jobs WHERE request_id=?", (request_id,)
            ).fetchone()
            if row is None:
                return None
            dataset_row(connection, row["dataset_id"])
            if row["deleted"] or row["request_sha256"] != request_sha256:
                raise WebError(
                    409,
                    "sar_request_conflict",
                    "This analysis request identity has different parameters.",
                )
            return SARJob.model_validate_json(row["payload"])

    def create(
        self, job: SARJob, request_id: str, request_sha256: str, spec: dict, root: str
    ) -> SARJob:
        with self.store.connect(write=True) as connection:
            dataset_row(connection, job.dataset_id)
            previous = connection.execute(
                "SELECT * FROM jobs WHERE request_id=?", (request_id,)
            ).fetchone()
            if previous:
                if previous["deleted"] or previous["request_sha256"] != request_sha256:
                    raise WebError(
                        409,
                        "sar_request_conflict",
                        "Analysis request identity changed.",
                    )
                return SARJob.model_validate_json(previous["payload"])
            if connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] >= 2048:
                raise WebError(
                    413,
                    "sar_job_limit",
                    "SAR analysis retention limit has been reached.",
                )
            if (
                connection.execute(
                    "SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running')"
                ).fetchone()[0]
                >= 16
            ):
                raise WebError(409, "sar_queue_full", "SAR queue is full.")
            try:
                connection.execute(
                    "INSERT INTO jobs(id,dataset_id,request_id,request_sha256,status,spec,payload,root) VALUES(?,?,?,?,?,?,?,?)",
                    (
                        job.id,
                        job.dataset_id,
                        request_id,
                        request_sha256,
                        job.status,
                        encode(spec),
                        job.model_dump_json(),
                        root,
                    ),
                )
            except sqlite3.IntegrityError as error:
                raise WebError(
                    409,
                    "sar_active",
                    "This dataset already has an active SAR analysis.",
                ) from error
        return job

    def prepared(self, identifier: str) -> None:
        with self.store.connect(write=True) as connection:
            row = job_row(connection, identifier)
            if row["status"] != "queued" or row["cancel_requested"]:
                raise WebError(
                    409,
                    "sar_input_changed",
                    "SAR input publication was cancelled or changed.",
                )
            connection.execute(
                "UPDATE jobs SET ready=1 WHERE id=? AND ready=0", (identifier,)
            )

    def cleaned(self, identifier: str, attempt: str) -> None:
        with self.store.connect(write=True) as connection:
            row = job_row(connection, identifier)
            if json.loads(row["spec"])["attempt_id"] != attempt:
                raise WebError(
                    409,
                    "sar_attempt_changed",
                    "SAR attempt changed before cleanup publication.",
                )
            connection.execute(
                "UPDATE jobs SET cleanup_verified=1 WHERE id=?", (identifier,)
            )

    def record(self, identifier: str) -> dict:
        with self.store.connect() as connection:
            return dict(job_row(connection, identifier))

    def get(self, identifier: str) -> SARJob:
        return SARJob.model_validate_json(self.record(identifier)["payload"])

    def list(self, dataset_id: str) -> JobList:
        with self.store.connect() as connection:
            dataset_row(connection, dataset_id)
            items = [
                SARJob.model_validate_json(row[0])
                for row in connection.execute(
                    "SELECT payload FROM jobs WHERE dataset_id=? AND deleted=0 ORDER BY rowid DESC LIMIT 2048",
                    (dataset_id,),
                )
            ]
        return JobList(items=items, total=len(items))

    def claim(self) -> dict | None:
        with self.store.connect(write=True) as connection:
            row = connection.execute(
                "SELECT j.* FROM jobs j JOIN datasets d ON d.id=j.dataset_id WHERE d.deleted=0 AND j.status='queued' AND j.ready=1 ORDER BY j.rowid LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            value = SARJob.model_validate_json(row["payload"])
            value.status, value.started_at = "running", now()
            connection.execute(
                "UPDATE jobs SET status='running',payload=?,cleanup_verified=0 WHERE id=? AND status='queued'",
                (value.model_dump_json(), value.id),
            )
            result = dict(row)
            result["payload"], result["status"] = value.model_dump_json(), "running"
            return result

    def update(self, identifier: str, **changes) -> SARJob:
        with self.store.connect(write=True) as connection:
            row = job_row(connection, identifier)
            value = SARJob.model_validate_json(row["payload"])
            value = SARJob.model_validate({**value.model_dump(), **changes})
            connection.execute(
                "UPDATE jobs SET status=?,payload=? WHERE id=?",
                (value.status, value.model_dump_json(), identifier),
            )
        return value

    def cancel(self, identifier: str) -> SARJob:
        with self.store.connect(write=True) as connection:
            row = job_row(connection, identifier)
            value = SARJob.model_validate_json(row["payload"])
            if value.status == "queued":
                value.status, value.finished_at = "cancelled", now()
            elif value.status != "running":
                return value
            connection.execute(
                "UPDATE jobs SET cancel_requested=1,status=?,payload=? WHERE id=?",
                (value.status, value.model_dump_json(), identifier),
            )
        return value

    def resume(self, identifier: str) -> SARJob:
        with self.store.connect(write=True) as connection:
            row = job_row(connection, identifier)
            value = SARJob.model_validate_json(row["payload"])
            if value.status not in {"interrupted", "failed", "cancelled"}:
                raise WebError(
                    409, "sar_resume_state", "Only stopped SAR analyses can be resumed."
                )
            value.status, value.error_code, value.error_message, value.finished_at = (
                "queued",
                None,
                None,
                None,
            )
            value.started_at = None
            spec = json.loads(row["spec"])
            spec["attempt_id"] = uuid.uuid4().hex
            try:
                connection.execute(
                    "UPDATE jobs SET status='queued',cancel_requested=0,cleanup_verified=0,payload=?,spec=? WHERE id=?",
                    (value.model_dump_json(), encode(spec), identifier),
                )
            except sqlite3.IntegrityError as error:
                raise WebError(
                    409, "sar_active", "This dataset already has an active analysis."
                ) from error
        return value

    def publish(
        self,
        identifier: str,
        pairs: list[Pair],
        total: int,
        *,
        report_sha256: str | None = None,
    ) -> SARJob:
        identities = {(item.region_id, item.molecule_id) for item in pairs}
        if len(identities) != len(pairs) or (
            report_sha256 is None and len(pairs) != total
        ):
            raise WebError(
                502,
                "sar_result_incomplete",
                "SAR worker did not account for every candidate.",
            )
        with self.store.connect(write=True) as connection:
            row = job_row(connection, identifier)
            value = SARJob.model_validate_json(row["payload"])
            dataset = Dataset.model_validate_json(
                dataset_row(connection, value.dataset_id)["metadata"]
            )
            expected_pairs = (
                total - dataset.row_count if value.kind == "study" else total
            )
            if (
                row["status"] != "running"
                or row["cancel_requested"]
                or value.total != total
                or len(pairs) != expected_pairs
                or (value.kind == "study") != (report_sha256 is not None)
            ):
                raise WebError(
                    409,
                    "sar_result_changed",
                    "SAR task changed; result publication was refused.",
                )
            connection.execute("DELETE FROM pairs WHERE job_id=?", (identifier,))
            connection.executemany(
                "INSERT INTO pairs VALUES(?,?,?)",
                [
                    (identifier, i, pair.model_dump_json())
                    for i, pair in enumerate(pairs)
                ],
            )
            value.status, value.finished_at, value.processed = "complete", now(), total
            value.matched = sum(pair.match_status == "matched" for pair in pairs)
            connection.execute(
                "UPDATE jobs SET status='complete',payload=? WHERE id=?",
                (value.model_dump_json(), identifier),
            )
            if report_sha256 is not None:
                spec = json.loads(row["spec"])
                spec["report_sha256"] = report_sha256
                connection.execute(
                    "UPDATE jobs SET spec=? WHERE id=?", (encode(spec), identifier)
                )
        return value

    def pairs(self, identifier: str, page: int, page_size: int) -> PairPage:
        if not 1 <= page <= 25000 or not 1 <= page_size <= 200:
            raise WebError(422, "sar_page", "SAR result page exceeds its limit.")
        with self.store.connect() as connection:
            value = SARJob.model_validate_json(
                job_row(connection, identifier)["payload"]
            )
            if value.status != "complete":
                raise WebError(
                    409,
                    "sar_results_pending",
                    "Complete SAR results are not yet available.",
                )
            rows = connection.execute(
                "SELECT payload FROM pairs WHERE job_id=? ORDER BY ordinal LIMIT ? OFFSET ?",
                (identifier, page_size, (page - 1) * page_size),
            )
            items = [Pair.model_validate_json(row[0]) for row in rows]
            pair_count = connection.execute(
                "SELECT COUNT(*) FROM pairs WHERE job_id=?", (identifier,)
            ).fetchone()[0]
        return PairPage(
            items=items, total=pair_count, page=page, page_size=page_size, job=value
        )

    def remove(self, identifier: str) -> None:
        with self.store.connect(write=True) as connection:
            row = job_row(connection, identifier)
            value = SARJob.model_validate_json(row["payload"])
            if (
                value.status in {"queued", "running"}
                or value.error_code == "sar_process_unverified"
                or (value.started_at and not row["cleanup_verified"])
            ):
                raise WebError(
                    409,
                    "sar_active",
                    "Only stopped, cleanup-verified SAR task records can be removed.",
                )
            connection.execute("UPDATE jobs SET deleted=1 WHERE id=?", (identifier,))
