"""Read-only actual transformation preview using the existing strict graph engine."""

from __future__ import annotations

import math
from decimal import localcontext

from ...core.sar.errors import SARInputError
from ...core.sar.matching import compile_reference
from ...core.sar.statistics import compare_observations
from ...core.sar.study_conditions import declared_observation
from ...core.sar.study_contexts import context_observations
from ...core.sar.study_graphs import cut_identity
from ...core.sar.values import Value, grade_ranks, parse_value
from ..errors import WebError
from .models import Pair
from .preview_drawing import paired_drawings
from .preview_models import PreviewMeasurement, StudyPreview
from .preview_records import recorded_measurements
from .preview_source import PreviewSource, VerifiedPreview, load_source


def _scalar_difference(left: Value, right: Value) -> float | None:
    if left.kind != "scalar" or right.kind != "scalar":
        return None
    a, b = left.numeric_bounds()[0], right.numeric_bounds()[0]
    exponent_a, exponent_b = a.as_tuple().exponent, b.as_tuple().exponent
    if not isinstance(exponent_a, int) or not isinstance(exponent_b, int):
        return None
    # Parsed numbers already have bounded size/exponents. Exact subtraction
    # avoids turning close, high-precision measurements into a false zero.
    with localcontext() as context:
        context.prec = max(a.adjusted(), b.adjusted()) - min(exponent_a, exponent_b) + 2
        difference = b - a
        value = float(difference)
    if not math.isfinite(value) or (value == 0 and difference != 0):
        return None
    return value


def verified_preview(
    queue, source: PreviewSource, region_id: str, molecule_id: str
) -> VerifiedPreview:
    """The single retained graph/member/fragment/published-pair authority."""
    job, report, packet = source.job, source.report, source.packet
    identifier = job.id
    summary = source.summaries.get(region_id)
    if summary is None or len(molecule_id) > 200:
        raise WebError(
            422, "sar_preview_selection", "Choose a recorded study region and member."
        )
    region = summary.region
    members = {mid for fragment in summary.fragments for mid in fragment.molecule_ids}
    if (
        molecule_id not in report.molecule_ids
        or molecule_id not in members
        or molecule_id == region.molecule_id
    ):
        raise WebError(
            422,
            "sar_preview_selection",
            "Choose an actual non-reference strict member.",
        )
    reference, candidate = (
        source.sources[region.molecule_id],
        source.sources[molecule_id],
    )
    if region_id not in source.matchers:
        source.matchers[region_id] = compile_reference(
            reference["molfile"],
            region.atom_indices,
            hydrogen_anchor=region.hydrogen_anchor,
        )
    proof = source.matchers[region_id].compare_details(candidate["molfile"])
    if proof["match_status"] != "matched":
        raise WebError(
            409,
            "sar_preview_proof",
            "The complete fixed graph no longer proves this transformation.",
        )
    fragment = cut_identity(
        candidate["molfile"],
        proof["variable_atom_indices"],
        proof["attachment_mapping"],
        hydrogen_anchor=proof.get("candidate_hydrogen_anchor"),
    )
    if fragment[
        "fixed_background_sha256"
    ] != summary.fixed_background_sha256 or not any(
        item.id == fragment["id"]
        and molecule_id in item.molecule_ids
        and item.smiles == fragment["smiles"]
        and item.graph_smiles == fragment.get("graph_smiles")
        for item in summary.fragments
    ):
        raise WebError(
            409,
            "sar_preview_proof",
            "Fragment identity differs from its complete report.",
        )
    with queue.service.store.connect() as connection:
        saved = connection.execute(
            "SELECT payload FROM pairs WHERE job_id=? AND json_extract(payload,'$.region_id')=? AND json_extract(payload,'$.molecule_id')=?",
            (identifier, region_id, molecule_id),
        ).fetchall()
    if len(saved) != 1:
        raise WebError(
            409, "sar_preview_proof", "A unique published comparison is required."
        )
    pair = Pair.model_validate_json(saved[0][0])
    if (
        pair.reference_id != region.molecule_id
        or pair.fragment_id != fragment["id"]
        or pair.variable_atom_indices != proof["variable_atom_indices"]
        or pair.attachment_mapping != proof["attachment_mapping"]
        or pair.candidate_hydrogen_anchor != proof.get("candidate_hydrogen_anchor")
        or pair.match_status != "matched"
    ):
        raise WebError(
            409,
            "sar_preview_proof",
            "Published mapping differs from the strict graph proof.",
        )
    declarations = {
        item.context_id: item.model_dump() for item in report.context_declarations
    }
    contexts = {item.id: item for item in report.contexts}
    measurements = []
    for policy in report.policies:
        claim = declarations.get(policy.context_id)
        left = [
            declared_observation(obs, claim)
            for obs in context_observations(reference, policy.context_id)
        ]
        right = [
            declared_observation(obs, claim)
            for obs in context_observations(candidate, policy.context_id)
        ]
        compared = compare_observations(
            left,
            right,
            contexts[policy.context_id].metric_id,
            policy.direction,
            policy.grade_order,
            packet["request"]["confirm_context"],
        )
        if claim and compared["evidence_basis"] == "recorded_context":
            compared["evidence_basis"] = "source_declared"
        difference = None
        if compared["comparison"] in {"better", "worse", "equal"}:
            ranks = grade_ranks(policy.grade_order)
            a, b = (
                parse_value(left[0]["value"], ranks),
                parse_value(right[0]["value"], ranks),
            )
            difference = _scalar_difference(a, b)
        measurements.append(
            PreviewMeasurement(
                context_id=policy.context_id,
                reference_values=[obs["value"] for obs in left],
                candidate_values=[obs["value"] for obs in right],
                comparison=compared["comparison"],
                evidence_basis=compared["evidence_basis"],
                raw_difference=difference,
            )
        )
    ref, alt = source.rows[region.molecule_id], source.rows[molecule_id]
    differences = {}
    for key, first in ref.properties.items():
        second = alt.properties.get(key)
        same_origin = ref.property_origins.get(key) == alt.property_origins.get(key)
        property_difference = (
            second - first
            if first is not None and second is not None and same_origin
            else None
        )
        differences[key] = (
            property_difference
            if property_difference is None or math.isfinite(property_difference)
            else None
        )
    data = StudyPreview(
        job=job,
        region=region,
        reference=ref,
        candidate=alt,
        pair=pair,
        measurements=measurements,
        recorded_measurements=recorded_measurements(
            reference,
            candidate,
            report.contexts,
            {policy.context_id for policy in report.policies},
        ),
        property_differences=differences,
    )
    return VerifiedPreview(data, reference, candidate, proof)


def preview(queue, identifier: str, region_id: str, molecule_id: str) -> StudyPreview:
    selected = verified_preview(
        queue, load_source(queue, identifier), region_id, molecule_id
    )
    try:
        selected.data.drawings = paired_drawings(
            selected.reference, selected.candidate, selected.data.region, selected.proof
        )
    except (SARInputError, ValueError, RuntimeError, OverflowError) as error:
        raise WebError(
            422,
            "sar_structure_unavailable",
            "Paired structure drawing is unavailable; no chemical placeholder was substituted.",
        ) from error
    return selected.data
