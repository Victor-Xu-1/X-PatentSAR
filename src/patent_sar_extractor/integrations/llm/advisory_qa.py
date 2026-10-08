"""Source-led advisory findings through the sole consent/budget/API authority.

No model scores, free-form repairs, activity-led exclusions or sibling-ID
normalization. The original deterministic report is never changed here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from patent_sar_extractor.artifact_io import load_json, write_json_atomic
from patent_sar_extractor.contracts import (
    LLM_QA_REPORT_SCHEMA,
    LLM_QA_REPORT_SCHEMA_VERSION,
    artifact_identity,
)

from .config import get_evidence_resolution_config
from .evidence_protocol import EvidenceCandidate, EvidenceObservation, EvidenceRequest
from .evidence_resolution import EvidenceCallBudget, resolve_evidence
from .job_context import context_for_run


def _write_reports(base: Path, result: dict[str, Any]) -> None:
    write_json_atomic(base / "llm_qa_report.json", result)
    lines = [
        "# X-PatentSAR API evidence review",
        "",
        "Advisory only; source-led deterministic QA remains authoritative.",
        "",
        f"Status: {result['status']}",
        f"Reason: {result.get('reason', '')}",
        "",
    ]
    lines.extend(f"- {item}" for item in result["suggestions"])
    (base / "llm_qa_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_advisory_qa(output_dir: str, *, enabled: bool = True) -> dict[str, Any]:
    base = Path(output_dir)
    base.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {
        **artifact_identity(LLM_QA_REPORT_SCHEMA, LLM_QA_REPORT_SCHEMA_VERSION),
        "authority": "advisory",
        "status": "skipped_by_operator",
        "assessment": "unavailable",
        "score": None,
        "warnings": [],
        "suggestions": [],
        "details": {},
        "formal_acceptance_changed": False,
    }
    if enabled:
        try:
            policy = get_evidence_resolution_config()
            if policy.mode == "off" or not policy.data_consent:
                result.update(status="skipped_policy", reason="off_or_no_consent")
            else:
                formal = load_json(base / "final_qa_report.json", {})
                summary = load_json(base / "pipeline_summary.json", {})
                pdf = summary.get("input_pdf")
                if not isinstance(pdf, str) or not Path(pdf).is_file():
                    raise ValueError("Original QA source is unavailable")
                from patent_sar_extractor.core.page_ocr_cache import _pdf_sha256

                original = _pdf_sha256(pdf)
                context = context_for_run(str(base), original, policy=policy)
                errors = formal.get("acceptance", {}).get("hard_errors", [])
                if (
                    not isinstance(errors, list)
                    or len(errors) > 25000
                    or any(not isinstance(item, str) for item in errors)
                ):
                    raise ValueError("Invalid deterministic findings")
                findings = tuple(
                    item for item in dict.fromkeys(errors) if 0 < len(item) <= 1800
                )[:8]
                if not findings:
                    result.update(
                        status="skipped_no_findings",
                        reason="no_bounded_source_findings",
                    )
                else:
                    observations = tuple(
                        EvidenceObservation(f"qa:{i}", "text", text)
                        for i, text in enumerate(findings)
                    )
                    candidates = tuple(
                        EvidenceCandidate(
                            f"finding:{i}",
                            "Source-led original finding for manual review",
                            (f"qa:{i}",),
                        )
                        for i in range(len(findings))
                    )
                    request = EvidenceRequest(
                        context.job_id,
                        original,
                        "qa-findings",
                        observations,
                        candidates,
                        "on-error",
                    )
                    budget = EvidenceCallBudget(
                        context.job_id, context.policy.max_calls, ledger=context.ledger
                    )
                    review = resolve_evidence(
                        request,
                        budget,
                        config=context.policy,
                        require_complete_refs=True,
                    )
                    by_id = {item.candidate_id: i for i, item in enumerate(candidates)}
                    selected = [
                        findings[by_id[item.candidate_id]]
                        for item in review.candidates
                        if item.candidate_id in by_id
                        and item.observation_ids
                        == candidates[by_id[item.candidate_id]].observation_ids
                    ]
                    result.update(
                        status=review.status,
                        reason=review.reason,
                        calls_used=review.calls_used,
                        assessment="review" if selected else "unavailable",
                        suggestions=selected,
                    )
        except (OSError, ValueError, TypeError, KeyError):
            result.update(
                status="unavailable", reason="invalid_source_or_configuration"
            )
    _write_reports(base, result)
    return result
