"""Non-authoritative LLM review of completed pipeline artifacts."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from patent_sar_extractor.artifact_io import load_json, write_json_atomic
from patent_sar_extractor.contracts import (
    LLM_QA_REPORT_SCHEMA,
    LLM_QA_REPORT_SCHEMA_VERSION,
    artifact_identity,
)
from patent_sar_extractor.smiles_artifact import smiles_records

from .client import llm_chat
from .config import has_llm_key


logger = logging.getLogger(__name__)

QA_SYSTEM_PROMPT = """You review patent structure-activity extraction results.
This is an activity-led pipeline: active compound order is authoritative and
non-active structures are intentionally excluded. Identify plausible omissions
or inconsistencies and return concise JSON suggestions. Your result is advisory
only and never controls formal acceptance."""


def _normalize_cpd(value: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    match = re.search(
        r"(?:compound|cpd|example|实施例|化合物)\s*[-:]?\s*(\d+(?:-\d+)?)",
        text,
        re.IGNORECASE,
    )
    return f"Compound {match.group(1)}" if match else text


def _items_from_bindings(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("final_bindings", "bindings"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _collect_details(base: Path) -> dict[str, Any]:
    profile = load_json(base / "page_classification" / "page_classification.json", {})
    structures = load_json(base / "structures" / "metadata.json", {})
    bindings = _items_from_bindings(load_json(base / "structure_bindings" / "bindings.json", {}))
    smiles_payload = load_json(base / "smiles" / "smiles_results.json", {})
    activity = load_json(base / "activity" / "activity_data.json", {})
    smiles_rows = smiles_records(smiles_payload)
    activity_rows = activity.get("rows", []) if isinstance(activity, dict) else []
    active_cpds = {
        _normalize_cpd(value)
        for value in (activity.get("active_cpds", []) if isinstance(activity, dict) else [])
        if _normalize_cpd(value)
    }
    if not active_cpds:
        active_cpds = {
            _normalize_cpd(row.get("cpd", ""))
            for row in activity_rows
            if isinstance(row, dict) and _normalize_cpd(row.get("cpd", ""))
        }
    bound_cpds = {
        _normalize_cpd(row.get("cpd", ""))
        for row in bindings
        if _normalize_cpd(row.get("cpd", ""))
    }
    return {
        "synthesis_pages": len(profile.get("synthesis_pages", [])) if isinstance(profile, dict) else 0,
        "activity_pages": len(profile.get("activity_pages", [])) if isinstance(profile, dict) else 0,
        "structures": int(structures.get("total_structures", 0) or 0) if isinstance(structures, dict) else 0,
        "bindings": len(bindings),
        "smiles_records": len(smiles_rows),
        "valid_smiles": sum(1 for row in smiles_rows if row.get("rdkit_valid")),
        "activity_rows": len(activity_rows),
        "active_compounds": len(active_cpds),
        "active_without_structure": sorted(active_cpds - bound_cpds),
        "bound_without_activity": sorted(bound_cpds - active_cpds),
        "final_excel_present": any(
            path.is_file() and path.stat().st_size > 0
            for path in (base / "final_results").glob("*.xlsx")
        ),
        "final_sdf_present": any(
            path.is_file() and path.stat().st_size > 0
            for path in (base / "final_results").glob("*.sdf")
        ),
    }


def _parse_response(response: str) -> dict[str, Any] | None:
    candidates = [str(response or "").strip()]
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", str(response or ""), re.DOTALL)
    if fenced:
        candidates.insert(0, fenced.group(1))
    raw = str(response or "")
    if "{" in raw and "}" in raw:
        candidates.append(raw[raw.find("{") : raw.rfind("}") + 1])
    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(value, dict):
            return value
    return None


def _normalized_model_result(payload: dict[str, Any]) -> dict[str, Any]:
    warnings = payload.get("warnings", [])
    suggestions = payload.get("suggestions", [])
    score = payload.get("score")
    if not isinstance(warnings, list) or not isinstance(suggestions, list):
        raise ValueError("warnings and suggestions must be JSON arrays")
    if not isinstance(score, (int, float)) or isinstance(score, bool) or not 0 <= float(score) <= 100:
        raise ValueError("score must be a number from 0 through 100")
    return {
        "assessment": "pass" if payload.get("ok") is True else "review",
        "score": float(score),
        "warnings": [str(item).strip() for item in warnings if str(item).strip()],
        "suggestions": [str(item).strip() for item in suggestions if str(item).strip()],
    }


def _write_reports(base: Path, result: dict[str, Any]) -> None:
    write_json_atomic(base / "llm_qa_report.json", result)
    lines = [
        "# PatentSAR Extractor LLM Advisory QA",
        "",
        "This report is advisory and has no formal acceptance authority.",
        "",
        f"- Status: {result['status']}",
        f"- Assessment: {result['assessment']}",
        f"- Score: {result['score'] if result['score'] is not None else 'N/A'}",
        "",
        "## Warnings",
    ]
    lines.extend([f"- {item}" for item in result["warnings"]] or ["- None"])
    lines.extend(["", "## Suggestions"])
    lines.extend([f"- {item}" for item in result["suggestions"]] or ["- None"])
    lines.extend(["", "## Metrics"])
    lines.extend([f"- {key}: {value}" for key, value in result["details"].items()])
    (base / "llm_qa_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_advisory_qa(output_dir: str, *, enabled: bool = True) -> dict[str, Any]:
    """Run optional LLM review and persist a separate advisory report."""

    base = Path(output_dir)
    base.mkdir(parents=True, exist_ok=True)
    details = _collect_details(base)
    result: dict[str, Any] = {
        **artifact_identity(LLM_QA_REPORT_SCHEMA, LLM_QA_REPORT_SCHEMA_VERSION),
        "authority": "advisory",
        "status": "skipped_no_credentials",
        "assessment": "unavailable",
        "score": None,
        "warnings": [],
        "suggestions": [],
        "details": details,
    }
    if not enabled:
        result["status"] = "skipped_by_operator"
        _write_reports(base, result)
        logger.info("LLM advisory QA skipped by explicit operator policy")
        return result
    if not has_llm_key():
        _write_reports(base, result)
        logger.info("LLM advisory QA skipped: no configured credentials")
        return result

    prompt = (
        "Review this PatentSAR extraction summary and return only JSON with "
        'the shape {"ok": true, "score": 0, "warnings": [], "suggestions": []}.\n\n'
        + json.dumps(details, ensure_ascii=False, indent=2)
    )
    try:
        response = llm_chat(
            [
                {"role": "system", "content": QA_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            cache=True,
        )
    except Exception as exc:  # defensive boundary around an external service
        logger.warning("LLM advisory QA request failed: %s", exc)
        result["status"] = "request_failed"
        _write_reports(base, result)
        return result

    if not response:
        result["status"] = "request_failed"
        _write_reports(base, result)
        return result
    parsed = _parse_response(response)
    if parsed is None:
        result["status"] = "invalid_response"
        _write_reports(base, result)
        return result
    try:
        result.update(_normalized_model_result(parsed))
    except ValueError as exc:
        logger.warning("LLM advisory QA response rejected: %s", exc)
        result["status"] = "invalid_response"
        _write_reports(base, result)
        return result
    result["status"] = "completed"
    _write_reports(base, result)
    logger.info("LLM advisory QA completed (assessment=%s)", result["assessment"])
    return result
