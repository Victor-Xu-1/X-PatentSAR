"""Project-wide nomination admission delegates to the existing source authority.

This module never grants extraction acceptance, edits evidence or calls a model.
Manual review/property calculations and independent curated SAR remain separate.
"""

import json

from pydantic import ValidationError

from patent_sar_extractor import contracts as core

from .lead_models import LeadAssessment
from .models import Acceptance


def source_acceptance(project: dict) -> Acceptance:
    """Read-only fallback for cache consumers without a live service callback."""
    try:
        value = project.get("snapshot")
        if not isinstance(value, str) or len(value.encode()) > 32 * 1024 * 1024:
            raise ValueError("Missing or over-bound source snapshot")
        snapshot = json.loads(value)
        return Acceptance.model_validate(snapshot.get("acceptance"))
    except (ValueError, TypeError, AttributeError, RecursionError, ValidationError):
        return Acceptance(
            state="historical", errors=["Source acceptance is unavailable."]
        )


def source_ready(acceptance: Acceptance) -> bool:
    return acceptance.state == "accepted" and not acceptance.errors


def source_identity(project: dict, acceptance: Acceptance | None = None) -> list:
    decision = acceptance if acceptance is not None else source_acceptance(project)
    return [
        "accepted-source-corpus-v1",
        decision.model_dump(),
        core.pipeline_contract_ref(),
        core.ruleset_ref(),
        core.BINDINGS_SCHEMA_VERSION,
        core.STRUCTURE_BINDER_VERSION,
        core.ACTIVITY_SCHEMA_VERSION,
        core.ACTIVITY_EXTRACTOR_VERSION,
        core.ACTIVITY_COVERAGE_SCHEMA_VERSION,
        core.STEREO_EVIDENCE_VERSION,
        core.OCSR_PREPARATION_VERSION,
        core.QA_REPORT_SCHEMA_VERSION,
    ]


def blocked_assessment(acceptance: Acceptance) -> LeadAssessment:
    return LeadAssessment(
        status="unranked",
        warnings=[
            "来源任务未通过当前验收，暂不生成 Lead 候选。"
            if acceptance.state != "historical"
            else "历史来源仅供复核，暂不生成 Lead 候选。"
        ],
    )
