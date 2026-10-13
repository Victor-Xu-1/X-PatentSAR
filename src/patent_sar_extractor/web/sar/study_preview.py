"""Read-only actual transformation preview using the existing strict graph engine."""

from __future__ import annotations

from ...core.sar.errors import SARInputError
from ...core.sar.matching import compile_reference
from ...core.sar.measurements import parse_measurement, scalar_difference
from ...core.sar.statistics import compare_observations
from ...core.sar.study_conditions import declared_observation
from ...core.sar.study_contexts import context_observations
from ...core.sar.study_graphs import cut_identity
from ...core.sar.values import grade_ranks
from ..errors import WebError
from .models import Pair
from .preview_drawing import paired_drawings
from .preview_models import PreviewMeasurement, StudyPreview
from .preview_properties import property_comparisons
from .preview_records import recorded_measurements
from .preview_source import PreviewSource, VerifiedPreview, load_source


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
            # Archived inputs keep their captured comparison semantics. This
            # is a read adapter, never an alternative new-study engine.
            open_bounds=packet["schema"] >= 3,
            inline_units=packet["schema"] >= 4,
            declared_units=packet["schema"] >= 7,
        )
        if claim and compared["evidence_basis"] == "recorded_context":
            compared["evidence_basis"] = "source_declared"
        difference = None
        if compared["comparison"] in {"better", "worse", "equal"}:
            ranks = grade_ranks(policy.grade_order)
            a, b = (
                parse_measurement(
                    left[0]["value"],
                    ranks,
                    left[0].get("unit"),
                    inline_units=packet["schema"] >= 4,
                    declared_units=packet["schema"] >= 7,
                ),
                parse_measurement(
                    right[0]["value"],
                    ranks,
                    right[0].get("unit"),
                    inline_units=packet["schema"] >= 4,
                    declared_units=packet["schema"] >= 7,
                ),
            )
            difference = scalar_difference(a, b)
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
    properties = property_comparisons(ref, alt)
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
            differences=packet["schema"] >= 6,
            declared_units=packet["schema"] >= 7,
        ),
        property_differences=properties.differences,
        property_statuses=properties.statuses,
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
