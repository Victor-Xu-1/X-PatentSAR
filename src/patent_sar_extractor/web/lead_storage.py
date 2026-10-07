"""Rebuildable project-wide nomination cache, never formal QA or raw chemistry."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections.abc import Sequence
from datetime import datetime
from importlib.metadata import version

from pydantic import ValidationError

from .errors import WebError
from .lead_models import LEAD_POLICY_VERSION, LeadAssessment
from .models import Compound
from .property_values import effective_property_values
from .storage import Store, encode, now

POLICY_VERSION = LEAD_POLICY_VERSION
RDKIT_VERSION = version("rdkit")
MAX_REPORT_BYTES = 32 * 1024 * 1024
MAX_SOURCE_BYTES = 128 * 1024 * 1024


def input_fingerprint(project: dict, compounds: Sequence[Compound]) -> str:
    """Exact effective inputs; no paging, filter, timestamp or page-render identity."""
    digest = hashlib.sha256()
    digest.update(
        encode(
            [
                POLICY_VERSION,
                RDKIT_VERSION,
                project["id"],
                project["sha256"],
                project["run_root"],
            ]
        ).encode()
    )
    for item in sorted(compounds, key=lambda row: row.id):
        packet = {
            "id": item.id,
            "display_id": item.display_id,
            "structure_id": item.structure_id,
            "smiles": item.smiles,
            "molfile": item.structure_molfile,
            "recognition": item.recognition.model_dump(),
            "confidence": item.confidence.model_dump(),
            "source": item.source.model_dump(),
            "flags": item.flags,
            "record_kind": item.record_kind,
            "review": item.review.model_dump() if item.review else None,
            "correction": item.correction.model_dump() if item.correction else None,
            "activities": [value.model_dump() for value in item.activities],
            "properties": effective_property_values(item),
            "admet": item.admet.model_dump() if item.admet else None,
        }
        digest.update(encode(packet).encode())
        digest.update(b"\n")
    return digest.hexdigest()


def source_revision(connection: sqlite3.Connection, project_id: str) -> str:
    """CAS over all relevant persisted authorities in one short SQLite snapshot."""
    digest = hashlib.sha256()
    used = 0
    queries = (
        "SELECT id,sha256,expected_sha256,run_root,snapshot FROM projects WHERE id=?",
        "SELECT id,ordinal,payload,image_path,geometry_space FROM compounds WHERE project_id=? ORDER BY id",
        "SELECT compound_id,revision,fields,basis_fingerprint FROM corrections WHERE project_id=? ORDER BY compound_id",
        "SELECT compound_id,decision,revision FROM reviews WHERE project_id=? ORDER BY compound_id",
        "SELECT compound_id,source_fingerprint,crop_sha256,observation FROM compound_recognitions WHERE project_id=? ORDER BY compound_id",
        "SELECT compound_id,source_fingerprint,smiles_sha256,epoch,updated_at FROM admet_predictions WHERE project_id=? ORDER BY compound_id,source_fingerprint,smiles_sha256,epoch",
        "SELECT compound_id,source_fingerprint,smiles_sha256,epoch,updated_at FROM molecular_descriptors WHERE project_id=? ORDER BY compound_id,source_fingerprint,smiles_sha256,epoch",
    )
    for query in queries:
        for row in connection.execute(query, (project_id,)):
            data = encode(list(row)).encode()
            used += len(data)
            if used > MAX_SOURCE_BYTES:
                raise WebError(
                    413,
                    "lead_input_limit",
                    "Lead inputs exceed their bounded snapshot size.",
                )
            digest.update(data)
            digest.update(b"\n")
    return digest.hexdigest()


class LeadStore:
    def __init__(self, store: Store) -> None:
        self.store = store
        with store.connect(write=True) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS lead_selections ("
                "project_id TEXT PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,"
                "input_fingerprint TEXT NOT NULL,payload TEXT NOT NULL,updated_at TEXT NOT NULL)"
            )

    def revision(self, project_id: str) -> str:
        with self.store.connect() as connection:
            connection.execute("BEGIN")
            return source_revision(connection, project_id)

    def has_report(self, project_id: str) -> bool:
        with self.store.connect() as connection:
            return (
                connection.execute(
                    "SELECT 1 FROM lead_selections WHERE project_id=?", (project_id,)
                ).fetchone()
                is not None
            )

    def report(self, project_id: str) -> dict | None:
        with self.store.connect() as connection:
            row = connection.execute(
                "SELECT * FROM lead_selections WHERE project_id=?", (project_id,)
            ).fetchone()
        if row is None:
            return None
        try:
            if len(row["payload"].encode()) > MAX_REPORT_BYTES:
                raise ValueError("Oversized Lead report")
            report = json.loads(row["payload"])
            if (
                not isinstance(report, dict)
                or set(report)
                != {
                    "schema",
                    "policy_version",
                    "rdkit_version",
                    "project_id",
                    "input_fingerprint",
                    "job_id",
                    "generated_at",
                    "review_only",
                    "status",
                    "error_code",
                    "items",
                }
                or not isinstance(report["schema"], dict)
                or type(report["schema"].get("version")) is not int
                or not isinstance(report["input_fingerprint"], str)
                or not re.fullmatch(r"[a-f0-9]{64}", report["input_fingerprint"])
                or (
                    report["job_id"] is not None
                    and (
                        not isinstance(report["job_id"], str)
                        or not re.fullmatch(r"[a-f0-9]{32}", report["job_id"])
                    )
                )
                or not isinstance(report["generated_at"], str)
                or len(report["generated_at"]) > 100
                or datetime.fromisoformat(report["generated_at"]).tzinfo is None
                or (
                    report["status"] == "failed"
                    and (
                        not isinstance(report["error_code"], str)
                        or not re.fullmatch(r"[a-z0-9_]{1,100}", report["error_code"])
                    )
                )
                or (report["status"] == "complete" and report["error_code"] is not None)
                or any(not key or len(key) > 200 for key in report["items"])
                or report["schema"]
                != {"name": "patentsar.lead-selection", "version": 1}
                or report["policy_version"] != POLICY_VERSION
                or not isinstance(report["rdkit_version"], str)
                or not 1 <= len(report["rdkit_version"]) <= 40
                or report["project_id"] != project_id
                or report["input_fingerprint"] != row["input_fingerprint"]
                or report["review_only"] is not True
                or not isinstance(report["items"], dict)
                or len(report["items"]) > 25000
                or report["status"] not in {"complete", "failed"}
            ):
                raise ValueError("Invalid Lead report envelope")
            assessments = {
                key: LeadAssessment.model_validate(value)
                for key, value in report["items"].items()
            }
            ranks = sorted(
                value.rank
                for value in assessments.values()
                if value.status == "selected"
            )
            if ranks != list(range(1, len(ranks) + 1)) or len(ranks) > 8:
                raise ValueError("Invalid Lead selection ranks")
            if report["status"] == "failed" and assessments:
                raise ValueError("Failed Lead report cannot contain nominations")
            return report
        except (
            ValueError,
            KeyError,
            TypeError,
            RecursionError,
            ValidationError,
        ) as exc:
            raise WebError(
                422,
                "lead_record_invalid",
                "Saved Lead evidence failed validation; retain it for recovery.",
            ) from exc

    def attach(self, project: dict, compounds: Sequence[Compound]) -> None:
        try:
            report = self.report(project["id"])
        except WebError as exc:
            if exc.code != "lead_record_invalid":
                raise
            # A rebuildable recommendation cache cannot hide patent evidence.
            # It also cannot provide any candidate or pass job confirmation.
            for item in compounds:
                item.lead = LeadAssessment(
                    status="unranked",
                    warnings=[
                        "lead_record_invalid：Lead 记录未通过校验，未展示候选；请重新评估。"
                    ],
                )
            return
        if report is None:
            for item in compounds:
                item.lead = LeadAssessment()
            return
        current = report["input_fingerprint"] == input_fingerprint(project, compounds)
        for item in compounds:
            if not current:
                item.lead = LeadAssessment(
                    status="stale", warnings=["输入已变化，Lead 候选待重新评估。"]
                )
            elif report["status"] == "failed":
                item.lead = LeadAssessment(
                    status="unranked", warnings=["Lead 评估失败，未发布候选。"]
                )
            else:
                raw = report["items"].get(item.id)
                if raw is None:
                    raise WebError(
                        422,
                        "lead_record_invalid",
                        "Lead report does not cover the full project.",
                    )
                item.lead = LeadAssessment.model_validate(raw)

    def publish(
        self,
        project_id: str,
        fingerprint: str,
        revision: str,
        assessments: dict[str, LeadAssessment],
        *,
        job_id: str | None,
        failure: str | None = None,
    ) -> dict:
        report = {
            "schema": {"name": "patentsar.lead-selection", "version": 1},
            "policy_version": POLICY_VERSION,
            "rdkit_version": RDKIT_VERSION,
            "project_id": project_id,
            "input_fingerprint": fingerprint,
            "job_id": job_id,
            "generated_at": now(),
            "review_only": True,
            "status": "failed" if failure else "complete",
            "error_code": failure,
            "items": {key: value.model_dump() for key, value in assessments.items()},
        }
        payload = encode(report)
        if len(payload.encode()) > MAX_REPORT_BYTES:
            raise WebError(413, "lead_report_limit", "Lead report exceeds its bound.")
        with self.store.connect(write=True) as connection:
            if source_revision(connection, project_id) != revision:
                raise WebError(
                    409,
                    "lead_inputs_changed",
                    "Lead inputs changed during evaluation; no candidates were published.",
                )
            if job_id is not None:
                owner = connection.execute(
                    "SELECT project_id,status,cancel_requested FROM jobs WHERE id=?",
                    (job_id,),
                ).fetchone()
                if (
                    owner is None
                    or owner["project_id"] != project_id
                    or owner["status"] not in {"running", "complete", "failed"}
                    or owner["cancel_requested"]
                ):
                    raise WebError(
                        409,
                        "lead_owner_changed",
                        "Lead task ownership changed; no candidates were published.",
                    )
            connection.execute(
                "INSERT INTO lead_selections VALUES(?,?,?,?) ON CONFLICT(project_id) DO UPDATE SET input_fingerprint=excluded.input_fingerprint,payload=excluded.payload,updated_at=excluded.updated_at",
                (project_id, fingerprint, payload, report["generated_at"]),
            )
        return report
