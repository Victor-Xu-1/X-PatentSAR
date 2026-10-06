"""activity policy: single application-layer policy authority."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from patent_sar_extractor.artifact_io import load_json as _load_json
from patent_sar_extractor.artifact_io import write_json_atomic as _write_json
from patent_sar_extractor.contracts import (
    ACTIVITY_SCHEMA,
    ACTIVITY_SCHEMA_VERSION,
    artifact_identity,
    artifact_identity_matches,
)
from patent_sar_extractor.core.activity_identity import normalize_compound
from patent_sar_extractor.core.activity_values import has_usable_activity_values

logger = logging.getLogger("patent_sar_extractor")
WORKING_ROOT = Path.cwd()


def _normalize_cpd_label(value: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return ""
    if re.fullmatch(
        r"(?:claim\s*1\s+compound|claimed\s+compound|main\s+compound|single(?:ton)?\s+compound)",
        text,
        re.IGNORECASE,
    ):
        return "Claim 1 compound"
    return normalize_compound(text) or text


def _expand_cpd_labels(value: str) -> list[str]:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return []
    if re.search(
        r"^(?:ref\.?\s*\d+|reference\b|vehicle\b|dmso\b|control\b|nab[-\s]?paclitaxel\b|paclitaxel\b)",
        text,
        re.IGNORECASE,
    ):
        return []

    # A composite printed row is not evidence that each child was measured.
    normalized = _normalize_cpd_label(text)
    return [normalized] if normalized else []


def _cpd_sort_key(value: str):
    parts = re.findall(r"\d+|\D+", value)
    return [int(p) if p.isdigit() else p.lower() for p in parts]


def _has_activity_payload(row: dict) -> bool:
    if not isinstance(row, dict):
        return False
    for bucket_name in ("activity_values", "cell_line_data"):
        bucket = row.get(bucket_name, {}) or {}
        if not isinstance(bucket, dict):
            continue
        if has_usable_activity_values(bucket):
            return True
    return False


def _extract_active_cpds(activity_payload: dict) -> list[str]:
    active = []
    seen = set()
    if not isinstance(activity_payload, dict):
        return []
    for row in activity_payload.get("rows", []):
        if not _has_activity_payload(row):
            continue
        for cpd in _expand_cpd_labels(row.get("cpd", "")):
            if cpd not in seen:
                active.append(cpd)
                seen.add(cpd)
    data_map = activity_payload.get("data", {})
    if isinstance(data_map, dict):
        for raw_cpd, values in data_map.items():
            if has_usable_activity_values(values):
                for cpd in _expand_cpd_labels(raw_cpd):
                    if cpd not in seen:
                        active.append(cpd)
                        seen.add(cpd)
    return active


def _annotate_activity_payload(path: str) -> list[str]:
    payload = _load_json(path, {})
    active_cpds = _extract_active_cpds(payload)
    if isinstance(payload, dict):
        changed = payload.get("active_cpds") != active_cpds
        payload["active_cpds"] = active_cpds
        for key, value in artifact_identity(
            ACTIVITY_SCHEMA, ACTIVITY_SCHEMA_VERSION
        ).items():
            if payload.get(key) != value:
                payload[key] = value
                changed = True
        payload.setdefault("metadata", {})
        if isinstance(payload["metadata"], dict) and payload["metadata"].get(
            "n_active_cpds"
        ) != len(active_cpds):
            payload["metadata"]["n_active_cpds"] = len(active_cpds)
            changed = True
        if changed:
            _write_json(path, payload)
    return active_cpds


def _activity_acceptance_errors(
    activity_payload: dict,
    active_cpds: list[str],
    *,
    classified_activity_pages: list[int] | None = None,
) -> list[str]:
    if not isinstance(activity_payload, dict):
        return ["Activity extraction output is missing or malformed."]
    errors = []
    if not artifact_identity_matches(
        activity_payload, ACTIVITY_SCHEMA, ACTIVITY_SCHEMA_VERSION
    ):
        errors.append(
            "Activity output does not match the current activity schema and ruleset."
        )
    rows = activity_payload.get("rows", [])
    if not isinstance(rows, list):
        return [*errors, "Activity rows are malformed."]
    if not rows:
        if classified_activity_pages == [] and not active_cpds:
            return errors
        errors.append(
            "No activity rows were extracted without proof that activity is absent."
        )
        return errors
    active_set = set(active_cpds)
    review_cpds = [
        _normalize_cpd_label(row.get("cpd", ""))
        for row in rows
        if isinstance(row, dict)
        and row.get("needs_review")
        and _has_activity_payload(row)
        and any(cpd in active_set for cpd in _expand_cpd_labels(row.get("cpd", "")))
    ]
    if review_cpds:
        errors.append(
            f"Activity rows require review before binding ({review_cpds[:12]})."
        )
    if not active_cpds:
        errors.append("No compound with usable activity values was extracted.")
    if len(active_cpds) != len(set(active_cpds)):
        errors.append("Active compound list contains duplicate identifiers.")
    return errors
