"""Progress from persisted core stage facts, never inferred percentages."""

from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from patent_sar_extractor import contracts as core

from .errors import WebError
from .files import SafeFiles
from .models import STAGES, ActivityRepair, Stage, StageProgress

logger = logging.getLogger(__name__)
MAX_PROGRESS_BYTES = 8192
STAGE_STATUSES = {"pending", "running", "ok", "empty", "failed", "warnings"}
SUMMARY_STATUSES = {
    "running",
    "qa_pending",
    "complete",
    "review",
    "failed",
    "failed_accuracy_gate",
    "failed_qa",
}


def recorded_stage_order(summary: dict) -> list[str] | None:
    value = summary.get("main_chain")
    if (
        isinstance(value, list)
        and len(value) == len(STAGES)
        and all(isinstance(v, str) for v in value)
        and set(value) == set(STAGES)
    ):
        return value
    return None


def completed_stage_payloads(payloads: dict[str, Any]) -> dict[str, Any]:
    """Only the sole CLI's completed stages can publish current chemistry."""
    summary = payloads.get("summary")
    if not core.artifact_identity_matches(
        summary, core.RUN_SUMMARY_SCHEMA, core.RUN_SUMMARY_SCHEMA_VERSION
    ) or summary.get("status") in {"complete", "review"}:
        return payloads
    result = dict(payloads)
    steps = summary.get("steps", {})
    for artifact, stage in (
        ("activity", "activity"),
        ("locator", "locate"),
        ("structures", "structures"),
        ("bindings", "bind"),
        ("smiles", "smiles"),
        ("qa", "qa"),
    ):
        fact = steps.get(stage, {}) if isinstance(steps, dict) else {}
        if not isinstance(fact, dict) or (
            fact.get("status") not in {"ok", "empty", "warnings"}
            and not (
                fact.get("status") == "failed" and fact.get("output_updated") is True
            )
        ):
            result[artifact] = None
    return result


def read_summary(run_root: Path) -> dict[str, Any] | None:
    """An absent/corrupt summary is unavailable evidence, never success."""
    try:
        summary = SafeFiles(run_root).json("pipeline_summary.json")
    except WebError as exc:
        logger.warning("Stage summary unavailable (%s)", exc.code)
        return None
    if (
        not isinstance(summary, dict)
        or summary.get("schema")
        != core.schema_ref(core.RUN_SUMMARY_SCHEMA, core.RUN_SUMMARY_SCHEMA_VERSION)
        or not isinstance(summary.get("steps"), dict)
        or len(summary["steps"]) > len(STAGES)
        or any(name not in STAGES for name in summary["steps"])
        or any(not isinstance(step, dict) for step in summary["steps"].values())
        or any(
            not isinstance(step.get("status"), str)
            or step["status"] not in STAGE_STATUSES
            for step in summary["steps"].values()
        )
        or any(
            not isinstance(summary.get(key), dict)
            for key in ("product", "pipeline_contract", "ruleset")
        )
        or type(summary["schema"].get("version")) is not int
        or not isinstance(summary.get("status"), str)
        or summary["status"] not in SUMMARY_STATUSES
    ):
        return None
    return summary


def read_progress(files: SafeFiles, stage: str = "smiles") -> StageProgress | None:
    if stage not in {"smiles", "structures"}:
        return None
    try:
        payload = json.loads(
            files.read(f"{stage}/progress.json", max_bytes=MAX_PROGRESS_BYTES)
        )
        schema = payload.get("schema") if isinstance(payload, dict) else None
        if (
            not isinstance(payload, dict)
            or not isinstance(schema, dict)
            or type(schema.get("version")) is not int
            or payload.pop("schema", None)
            != core.schema_ref(
                core.STAGE_PROGRESS_SCHEMA, core.STAGE_PROGRESS_SCHEMA_VERSION
            )
            or payload.pop("stage", None) != stage
        ):
            return None
        # Strict counters do not coerce booleans/strings, and JSON NaN is rejected
        # by the finite DTO. Readers hold one descriptor across atomic replaces.
        if payload.get("peak_rss_mb") is not None and type(
            payload["peak_rss_mb"]
        ) not in {int, float}:
            return None
        progress = StageProgress.model_validate(payload)
        return progress
    except (WebError, ValueError, RecursionError, UnicodeError, ValidationError):
        # Progress is optional observation, not an execution or acceptance gate.
        return None


def stages_from_summary(
    summary: dict[str, Any], files: SafeFiles | None = None
) -> list[Stage]:
    steps = summary["steps"]
    counts = {
        "classify": "page_count",
        "activity": "rows",
        "locate": "selected_pages",
        "structures": "total",
        "bind": "bound",
        "smiles": "total",
        "final": "rows",
        "qa": "count",
    }
    output = []
    for name in recorded_stage_order(summary) or STAGES:
        raw = steps.get(name, {})
        if not isinstance(raw, dict):
            raw = {}
        status = raw.get("status", "pending")
        if status not in STAGE_STATUSES:
            raise ValueError("Stages require a validated pipeline summary")
        count = raw.get(counts[name])
        if isinstance(count, list):
            count = len(count)
        if (
            not isinstance(count, int)
            or isinstance(count, bool)
            or not 0 <= count <= 1000000
        ):
            count = None
        duration = raw.get("elapsed_s")
        if (
            not isinstance(duration, (int, float))
            or isinstance(duration, bool)
            or not math.isfinite(duration)
            or duration < 0
        ):
            duration = None
        output.append(
            Stage(
                name=name,
                status=status,
                count=count,
                duration_seconds=duration,
                reused_checkpoint=any(
                    raw.get(key) is True for key in ("from_cache", "cache", "reused")
                ),
                progress=(
                    read_progress(files, name)
                    if files is not None
                    and name in {"smiles", "structures"}
                    and status != "pending"
                    else None
                ),
                resource_wait=(
                    read_resource_wait(files, name)
                    if files and status == "running"
                    else None
                ),
                repair=read_repair(raw) if name == "activity" else None,
            )
        )
    return output


def read_repair(raw: dict) -> ActivityRepair | None:
    if "repair" not in raw:
        return None
    try:
        return ActivityRepair.model_validate(raw["repair"])
    except ValidationError:
        logger.warning(
            "Activity repair counters unavailable; original stage state retained"
        )
        return None


def read_resource_wait(files: SafeFiles, stage: str):
    from .resource_progress import read_wait

    return read_wait(files, stage)
