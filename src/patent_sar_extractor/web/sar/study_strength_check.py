"""Verify captured tiers through the same authority, never trust worker colors."""

from ...workers.study_candidates import collect_activities
from ...workers.study_strength import resolve_strength
from ..errors import WebError
from .study_models import StudyResultPolicy


def verify_strength(report, packet, request):
    observations, assessments = collect_activities(
        packet["molecules"],
        [p.model_dump() for p in request.policies],
        request.confirm_context,
        [d.model_dump() for d in request.context_declarations],
    )
    policies = resolve_strength(
        [p.model_dump() for p in request.policies],
        [c.model_dump() for c in report.contexts],
        observations,
        assessments,
    )
    expected = [StudyResultPolicy.model_validate(p) for p in policies]
    primary = policies[0]["context_id"]
    if report.policies != expected or any(
        row.strong != assessments[primary][row.molecule_id]["strong"]
        or row.activity_bands
        != {
            p["context_id"]: assessments[p["context_id"]][row.molecule_id]["band"]
            for p in policies
        }
        for row in report.rows
    ):
        raise WebError(
            502,
            "sar_result_invalid",
            "Study strength anchor or tiers differ from immutable whole-context measurements.",
        )
