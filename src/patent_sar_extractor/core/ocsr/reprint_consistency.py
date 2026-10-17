"""Recheck every additional original graph without choosing a winning depiction."""

from __future__ import annotations

from patent_sar_extractor.core.pipeline_rules import _label_key
from patent_sar_extractor.smiles_artifact import (
    smiles_records,
    smiles_reprint_records,
    smiles_source_records,
)

from .recognition_inputs import RecognitionPlan, ordered_source_results
from .recognition_policy import record_errors

REPRINT_REVIEW_FLAG = "source_reprint_review"


def reprint_findings(plan: RecognitionPlan, payload: dict) -> dict[str, list[str]]:
    """Full plain-SMILES identity only after independent raw/source QC.

    Canonical isomeric graphs retain stereo assignment, isotope, formal charge
    and every component. No tautomer/salt stripping, similarity, confidence vote,
    saved success flag or InChIKey substitutes for this equality. Plain OCSR QC
    rejects CX/unsupported encodings rather than flattening their extra meaning.
    """
    observations = smiles_reprint_records(payload)
    labels = list(
        dict.fromkeys(
            _label_key(str(row.get("cpd") or row.get("compound_id") or ""))
            for row in plan.reprints
        )
    )
    owners = set(labels)
    if observations and any(
        _label_key(str(row.get("cpd_id") or "")) not in owners for row in observations
    ):
        raise ValueError("Reprint recognition contains a foreign printed owner.")
    if not ordered_source_results(plan.reprints, observations):
        return {
            label: [
                "Reprint recognition does not cover the exact ordered original sources."
            ]
            for label in labels
        }
    if not plan.reprints:
        return {}
    primaries = {
        _label_key(str(row.get("cpd_id") or "")): row
        for row in [*smiles_records(payload), *smiles_source_records(payload)]
    }
    bindings = {
        _label_key(str(row.get("cpd") or row.get("compound_id") or "")): row
        for row in [*plan.formal, *plan.supplemental]
    }
    primary_errors = {}
    findings = {}
    for source, record in zip(plan.reprints, observations, strict=True):
        label = _label_key(str(source.get("cpd") or source.get("compound_id") or ""))
        primary = primaries.get(label, {})
        if label not in primary_errors:
            primary_errors[label] = record_errors(primary, bindings.get(label))
        reasons = record_errors(record, source)
        if primary_errors[label]:
            reasons.append(
                "The primary original source has no qualified chemical graph."
            )
        if not reasons and record["canonical_smiles"] != primary["canonical_smiles"]:
            reasons.append(
                "Original depictions disagree in complete chemical or stereochemical identity."
            )
        if reasons:
            findings.setdefault(label, []).extend(
                f"{source['structure_id']}: {reason}" for reason in reasons
            )
    return findings
