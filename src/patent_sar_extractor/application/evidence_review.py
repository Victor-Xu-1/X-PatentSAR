"""One optional, consent-gated evidence review before recognition.

Selections are proposals, never a second artifact writer or acceptance authority.
Raw cells, identifiers, images and deterministic errors cannot be edited here.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
from pathlib import Path

from patent_sar_extractor.artifact_io import write_json_atomic
from patent_sar_extractor.core.page_ocr_cache import _pdf_sha256
from patent_sar_extractor.integrations.llm.config import get_evidence_resolution_config
from patent_sar_extractor.integrations.llm.evidence_resolution import (
    EvidenceCallBudget,
    EvidenceCandidate,
    EvidenceObservation,
    EvidenceRequest,
    resolve_evidence,
)
from patent_sar_extractor.integrations.llm.job_context import context_for_run
from patent_sar_extractor.integrations.llm.private_state import read_private

from .pipeline_context import PipelineContext

_MAX_ROWS = 25000
_MAX_COLUMNS = 8
logger = logging.getLogger(__name__)


def _column_candidates(payload: dict, quality: bool) -> tuple:
    """One exact-context physical column, not every measured row or whole PDF."""
    observations, candidates, seen = [], [], set()
    rows = payload.get("rows", [])
    if not isinstance(rows, list) or len(rows) > _MAX_ROWS:
        return (), ()
    # Quality review remains bounded, but unresolved rows precede easy first rows.
    ordered = (
        sorted(
            rows,
            key=lambda row: (
                not (isinstance(row, dict) and row.get("needs_review") is True)
            ),
        )
        if quality
        else rows
    )
    for row in ordered:
        if not isinstance(row, dict) or (not quality and not row.get("needs_review")):
            continue
        sources = row.get("activity_sources", [])
        if not isinstance(sources, list):
            continue
        for source in sources[:8]:
            if not isinstance(source, dict):
                continue
            header_region = source.get("header_region")
            if (
                not isinstance(header_region, dict)
                or type(header_region.get("page_no")) is not int
                or header_region["page_no"] < 1
            ):
                continue
            header_bbox = header_region.get("bbox")
            if (
                not isinstance(header_bbox, list)
                or len(header_bbox) != 4
                or any(
                    type(v) not in (int, float) or not math.isfinite(v) or v < 0
                    for v in header_bbox
                )
            ):
                continue
            if header_bbox[0] >= header_bbox[2] or header_bbox[1] >= header_bbox[3]:
                continue
            cells = source.get("cells", [])
            if not isinstance(cells, list):
                continue
            ordered_cells = sorted(
                cells[:64],
                key=lambda cell: (
                    not (
                        isinstance(cell, dict)
                        and "unknown" in str(cell.get("field", "")).lower()
                    )
                ),
            )
            for cell in ordered_cells:
                if not isinstance(cell, dict) or cell.get("field") == "compound_id":
                    continue
                field = cell.get("field")
                raw = cell.get("raw_header")
                if (
                    not isinstance(field, str)
                    or not isinstance(raw, str)
                    or not raw.strip()
                ):
                    continue
                physical = cell.get("physical_column")
                if type(physical) is not int or not 0 <= physical < 64:
                    continue
                context = (
                    source.get("table_id"),
                    source.get("assay"),
                    source.get("target"),
                )
                key = json.dumps(
                    [context, header_region, physical, field], ensure_ascii=False
                )
                if key in seen:
                    continue
                seen.add(key)
                digest = hashlib.sha256(key.encode()).hexdigest()[:24]
                header_id, region_id = f"header:{digest}", f"region:{digest}"
                description = json.dumps(
                    {
                        "page": header_region["page_no"],
                        "bbox": header_bbox,
                        "column": physical,
                        "table": source.get("table_id"),
                        "current_field": field,
                    },
                    ensure_ascii=False,
                )
                if len(raw) > 4096 or len(description) > 4096 or len(field) > 256:
                    continue
                observations.extend(
                    (
                        EvidenceObservation(header_id, "text", raw),
                        EvidenceObservation(region_id, "region", description),
                    )
                )
                candidates.append(
                    EvidenceCandidate(f"column:{digest}", field, (header_id, region_id))
                )
                if len(candidates) == _MAX_COLUMNS:
                    return tuple(observations), tuple(candidates)
    return tuple(observations), tuple(candidates)


def review_source_evidence(
    state: PipelineContext, activity_errors: list[str]
) -> dict | None:
    """OFF is zero network and zero output I/O; one budget owns enabled review."""
    try:
        policy = get_evidence_resolution_config()
        policy.validate()
    except (OSError, TypeError, ValueError, AttributeError):
        return {
            "status": "unavailable",
            "reason": "invalid_configuration",
            "authority": "advisory",
        }
    if policy.mode == "off":
        return None
    if not policy.data_consent:
        return {
            "status": "disabled",
            "reason": "data_consent_required",
            "authority": "advisory",
        }
    quality = policy.mode == "quality"
    if not quality and not activity_errors and not state.scientific_errors.get("bind"):
        return None
    observations, candidates = _column_candidates(state.activity_payload, quality)
    if not candidates:
        return {
            "status": "unavailable",
            "reason": "no_bounded_evidence_candidates",
            "authority": "advisory",
        }
    original = _pdf_sha256(state.args.pdf)
    try:
        context = context_for_run(state.base_dir, original, policy=policy)
        budget = EvidenceCallBudget(
            context.job_id, policy.max_calls, ledger=context.ledger
        )
    except (OSError, TypeError, ValueError):
        return {
            "status": "unavailable",
            "reason": "private_context_unavailable",
            "authority": "advisory",
        }
    request = EvidenceRequest(
        context.job_id,
        original,
        "column-mapping",
        observations,
        candidates,
        "quality" if quality else "on-error",
    )
    try:
        result = resolve_evidence(
            request, budget, config=context.policy, require_complete_refs=True
        )
    except (OSError, TypeError, ValueError):
        return {
            "status": "unavailable",
            "reason": "call_budget_unavailable",
            "authority": "advisory",
        }
    required = {item.candidate_id: set(item.observation_ids) for item in candidates}
    complete_refs = all(
        item.candidate_id in required
        and set(item.observation_ids) == required[item.candidate_id]
        for item in result.candidates
    )
    receipt = {
        "schema": {"name": "patentsar.evidence-resolution-review", "version": 1},
        "authority": "advisory",
        "original_sha256": request.original_sha256,
        "mode": policy.mode,
        "status": result.status if complete_refs else "invalid_response",
        "outcome": result.outcome if complete_refs else "failed",
        "reason": result.reason if complete_refs else "required_evidence_missing",
        "calls_used": result.calls_used,
        "candidates": [
            {
                "candidate_id": item.candidate_id,
                "observation_ids": list(item.observation_ids),
            }
            for item in result.candidates
            if complete_refs
        ],
        "source_candidates": [
            {
                "candidate_id": item.candidate_id,
                "label": item.label,
                "observation_ids": list(item.observation_ids),
            }
            for item in candidates
        ],
        "formal_acceptance_changed": False,
    }
    try:
        previous_path = Path(state.base_dir) / "evidence_resolution_review.json"
        if previous_path.exists():
            previous = read_private(previous_path, 131072)
            if previous.get("original_sha256") != original:
                raise ValueError("Foreign source receipt")
            receipt["header_resolutions"] = previous.get("header_resolutions", [])
        write_json_atomic(
            Path(state.base_dir) / "evidence_resolution_review.json", receipt
        )
    except (OSError, ValueError, TypeError) as exc:
        logger.warning(
            "Optional evidence receipt could not be published (%s)", type(exc).__name__
        )
        receipt.update(
            status="unavailable", outcome="failed", reason="receipt_publication_failed"
        )
    return {
        key: receipt[key]
        for key in (
            "authority",
            "mode",
            "status",
            "outcome",
            "reason",
            "calls_used",
            "formal_acceptance_changed",
        )
    }
