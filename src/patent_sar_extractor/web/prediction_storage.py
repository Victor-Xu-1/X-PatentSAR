"""Private indexed prediction projections with producer and current-source binding."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any

from pydantic import ValidationError

from .attempts import spec_record
from .dto import Error
from .errors import WebError
from .prediction_fields import prediction_epoch
from .prediction_models import PredictionSummary
from .processes import runtime_identity
from .storage import Store, encode, now

SCHEMA = """
CREATE TABLE IF NOT EXISTS admet_predictions (
 project_id TEXT NOT NULL REFERENCES projects(id), compound_id TEXT NOT NULL,
 source_fingerprint TEXT NOT NULL, smiles_sha256 TEXT NOT NULL, epoch TEXT NOT NULL,
 payload TEXT NOT NULL, updated_at TEXT NOT NULL, job_id TEXT REFERENCES jobs(id),
 PRIMARY KEY(project_id, compound_id, source_fingerprint, smiles_sha256, epoch)
)
"""
PACKET_SCHEMA = {"name": "patentsar.prediction-projection", "version": 1}
MAX_PACKET_BYTES = 256 * 1024


def smiles_digest(smiles: str) -> str:
    return hashlib.sha256(smiles.encode()).hexdigest()


def terminal_error(status: str, error: Error | None = None) -> Error:
    return error or Error(
        code=f"admet_{status}" if status != "complete" else "admet_incomplete",
        message="The ADMET producer stopped before this structure had a complete observation.",
    )


class PredictionStore:
    def __init__(self, store: Store) -> None:
        self.store = store
        self.epoch = prediction_epoch()
        with store.connect(write=True) as connection:
            connection.execute(SCHEMA)
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(admet_predictions)")
            }
            if "job_id" not in columns:
                # Additive draft-schema compatibility. Existing packets/epochs
                # cannot become current evidence by adding a nullable field.
                connection.execute(
                    "ALTER TABLE admet_predictions ADD COLUMN job_id TEXT REFERENCES jobs(id)"
                )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS prediction_producer ON admet_predictions(job_id)"
            )

    def summaries(
        self, project_id: str, inputs: list[tuple[str, str, str | None]]
    ) -> dict[str, PredictionSummary]:
        result = {}
        for offset in range(0, len(inputs), 100):
            chunk = inputs[offset : offset + 100]
            known = [item for item in chunk if item[2]]
            rows: dict[str, dict[str, Any]] = {}
            previous: set[str] = set()
            if known:
                values = ",".join("(?,?,?)" for _ in known)
                parameters: list[object] = []
                for compound_id, source, smiles in known:
                    assert smiles is not None
                    parameters.extend((compound_id, source, smiles_digest(smiles)))
                parameters.extend((project_id, project_id, self.epoch))
                with self.store.connect() as connection:
                    for row in connection.execute(
                        f"WITH wanted(compound_id,source_fingerprint,smiles_sha256) AS (VALUES {values}) "
                        "SELECT wanted.compound_id,p.payload,p.project_id,p.job_id,"
                        "j.status AS producer_status,j.project_id AS producer_project,j.spec AS producer_spec,"
                        "EXISTS(SELECT 1 FROM admet_predictions old WHERE old.project_id=? AND old.compound_id=wanted.compound_id) AS previous "
                        "FROM wanted LEFT JOIN admet_predictions p ON p.project_id=? AND p.epoch=? AND "
                        "p.compound_id=wanted.compound_id AND p.source_fingerprint=wanted.source_fingerprint AND p.smiles_sha256=wanted.smiles_sha256 "
                        "LEFT JOIN jobs j ON j.id=p.job_id",
                        parameters,
                    ):
                        if row["payload"] is not None:
                            rows[row["compound_id"]] = dict(row)
                        elif row["previous"]:
                            previous.add(row["compound_id"])
            for compound_id, source, smiles in chunk:
                result[compound_id] = self.current(
                    rows.get(compound_id),
                    source,
                    smiles,
                    previous=compound_id in previous,
                )
        return result

    def current(
        self,
        record: dict[str, Any] | None,
        source: str,
        smiles: str | None,
        *,
        previous: bool = False,
    ) -> PredictionSummary:
        if not smiles:
            return PredictionSummary(
                status="unavailable",
                error=Error(
                    code="smiles_required",
                    message="A validated structure is required for ADMET.",
                ),
            )
        digest = smiles_digest(smiles)
        if record is None:
            return PredictionSummary(status="stale" if previous else "not_run")
        try:
            payload = record["payload"]
            if not isinstance(payload, str) or len(payload.encode()) > MAX_PACKET_BYTES:
                raise ValueError("Oversized prediction record")
            packet = json.loads(payload)
            if (
                not isinstance(packet, dict)
                or set(packet)
                != {
                    "schema",
                    "runtime_identity",
                    "epoch",
                    "project_id",
                    "compound_id",
                    "observation",
                }
                or packet["schema"] != PACKET_SCHEMA
                or not isinstance(packet["schema"], dict)
                or type(packet["schema"].get("version")) is not int
                or packet["runtime_identity"] != runtime_identity()
                or packet["epoch"] != self.epoch
                or packet["project_id"] != record["project_id"]
                or packet["compound_id"] != record["compound_id"]
                or record["producer_project"] != record["project_id"]
            ):
                raise ValueError("Prediction envelope or producer differs")
            producer = spec_record(record["producer_spec"])
            summary = PredictionSummary.model_validate(packet["observation"])
            if (
                summary.source_fingerprint != source
                or summary.smiles_sha256 != digest
                or summary.job_id != record["job_id"]
                or producer.get("job_id") != summary.job_id
                or producer.get("project_id") != record["project_id"]
                or producer.get("include_admet") is not True
                or producer.get("runtime_identity") != runtime_identity()
                or record["producer_status"]
                not in {
                    "queued",
                    "running",
                    "complete",
                    "failed",
                    "cancelled",
                    "interrupted",
                }
                or (
                    producer.get("admet_compounds")
                    and record["compound_id"] not in producer["admet_compounds"]
                )
                or (
                    summary.status == "complete"
                    and record["producer_status"] == "queued"
                )
            ):
                raise ValueError("Prediction source or producer is invalid")
            if summary.status in {"pending", "running"} and record[
                "producer_status"
            ] not in {"queued", "running"}:
                return PredictionSummary(
                    status="failed",
                    source_fingerprint=source,
                    smiles_sha256=digest,
                    job_id=summary.job_id,
                    error=terminal_error(record["producer_status"]),
                )
            return summary
        except (
            ValidationError,
            ValueError,
            RecursionError,
            KeyError,
            TypeError,
            WebError,
        ):
            return PredictionSummary(
                status="failed",
                error=Error(
                    code="admet_record_invalid",
                    message="Saved ADMET evidence failed validation.",
                ),
            )

    def _packet(
        self, project_id: str, compound_id: str, summary: PredictionSummary
    ) -> str:
        packet = encode(
            {
                "schema": PACKET_SCHEMA,
                "runtime_identity": runtime_identity(),
                "epoch": self.epoch,
                "project_id": project_id,
                "compound_id": compound_id,
                "observation": summary.model_dump(),
            }
        )
        if len(packet.encode()) > MAX_PACKET_BYTES:
            raise WebError(
                413, "admet_record_limit", "Prediction observation exceeds its limit."
            )
        return packet

    def put(
        self, project_id: str, compound_id: str, summary: PredictionSummary
    ) -> None:
        from .correction_storage import CorrectionStorage, correction_source_fingerprint
        from .corrections import apply_correction
        from .models import Compound

        summary = PredictionSummary.model_validate_json(summary.model_dump_json())
        if (
            not summary.source_fingerprint
            or not summary.smiles_sha256
            or not summary.job_id
        ):
            raise WebError(
                409,
                "admet_binding",
                "Prediction storage requires source and producer identity.",
            )
        with self.store.connect(write=True) as connection:
            project, row, correction = CorrectionStorage.context(
                connection, project_id, compound_id
            )
            effective = apply_correction(
                project, row, correction, Compound.model_validate_json(row["payload"])
            )
            job = connection.execute(
                "SELECT * FROM jobs WHERE id=? AND project_id=?",
                (summary.job_id, project_id),
            ).fetchone()
            spec = spec_record(job["spec"]) if job is not None else {}
            if (
                not effective.smiles
                or correction_source_fingerprint(project, row)
                != summary.source_fingerprint
                or smiles_digest(effective.smiles) != summary.smiles_sha256
                or job is None
                or job["status"] != "running"
                or spec.get("include_admet") is not True
                or spec.get("job_id") != summary.job_id
                or spec.get("project_id") != project_id
                or spec.get("runtime_identity") != runtime_identity()
                or (
                    spec.get("admet_compounds")
                    and compound_id not in spec["admet_compounds"]
                )
            ):
                raise WebError(
                    409,
                    "admet_binding",
                    "Prediction source or owned producer changed before publication.",
                )
            connection.execute(
                "INSERT INTO admet_predictions(project_id,compound_id,source_fingerprint,smiles_sha256,epoch,payload,updated_at,job_id) "
                "VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(project_id,compound_id,source_fingerprint,smiles_sha256,epoch) DO UPDATE SET "
                "payload=excluded.payload,updated_at=excluded.updated_at,job_id=excluded.job_id",
                (
                    project_id,
                    compound_id,
                    summary.source_fingerprint,
                    summary.smiles_sha256,
                    self.epoch,
                    self._packet(project_id, compound_id, summary),
                    now(),
                    summary.job_id,
                ),
            )

    def finish_job(
        self,
        connection: sqlite3.Connection,
        job_id: str,
        status: str,
        error: Error | None,
    ) -> None:
        """Same job-finalization transaction; no pending producer survives a terminal state."""
        for row in connection.execute(
            "SELECT rowid,* FROM admet_predictions WHERE job_id=?", (job_id,)
        ).fetchall():
            try:
                packet = json.loads(row["payload"])
                observation = PredictionSummary.model_validate(packet["observation"])
            except (ValueError, TypeError, KeyError, ValidationError):
                continue  # Corrupt packets remain visibly invalid, never silently promoted.
            if observation.status not in {"pending", "running"}:
                continue
            result = PredictionSummary(
                status="failed",
                source_fingerprint=row["source_fingerprint"],
                smiles_sha256=row["smiles_sha256"],
                job_id=job_id,
                error=terminal_error(status, error),
            )
            connection.execute(
                "UPDATE admet_predictions SET payload=?,updated_at=? WHERE rowid=?",
                (
                    self._packet(row["project_id"], row["compound_id"], result),
                    now(),
                    row["rowid"],
                ),
            )
