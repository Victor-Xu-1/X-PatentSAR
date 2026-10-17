"""Single ordered-source and fresh molecular-QC authority for all consumers."""

from __future__ import annotations

from patent_sar_extractor.core.pipeline_rules import _label_key
from patent_sar_extractor.smiles_artifact import (
    smiles_artifact_is_current,
    smiles_records,
    smiles_source_records,
)

from .recognition_inputs import ordered_source_results, recognition_inputs
from .stereo_gate import validate_stereo_observation


def record_errors(record: dict, binding: dict | None = None) -> list[str]:
    if not isinstance(record, dict):
        raise ValueError("Malformed recognition record")  # noqa: TRY004 -- shared schema boundary
    errors = []
    try:
        checked, stereo = validate_stereo_observation(record, binding)
    except ValueError as exc:
        errors.append(f"source stereochemistry: {exc}")
        checked = {}
    else:
        if stereo["status"] in {"conflict", "ambiguous"}:
            errors.append(f"source stereochemistry: {stereo['reason']}")
    if (
        record.get("rdkit_valid") is not True
        or not record.get("canonical_smiles")
        or not checked.get("rdkit_valid")
    ):
        errors.append("no clean RDKit-valid SMILES")
    if (
        record.get("OCSR_quality_flag") != "ok"
        or record.get("OCSR_status") != "success"
        or checked.get("quality_flag") != "ok"
        or record.get("has_dummy_atom")
        or record.get("has_query_atom")
    ):
        errors.append(
            f"recognition requires review ({record.get('OCSR_quality_flag', '')})"
        )
    elements = record.get("suspicious_elements") or []
    if not isinstance(elements, list):
        errors.append("suspicious element observations are malformed")
    elif elements or checked.get("suspicious_elements"):
        errors.append("suspicious elements require review")
    return errors


def validate_strict_smiles_results(bindings: list, results: list) -> list[str]:
    """Primary rows are unique; reprint ownership is handled by its role projection."""
    expected = [
        (
            _label_key(str(row.get("cpd") or row.get("cpd_id") or "")),
            row.get("structure_id"),
        )
        for row in bindings
        if isinstance(row, dict)
    ]
    errors = []
    if (
        not ordered_source_results(bindings, results)
        or len(expected) != len(bindings)
        or any(not label or not image for label, image in expected)
        or len({label for label, _ in expected}) != len(expected)
        or len({image for _, image in expected}) != len(expected)
    ):
        errors.append(
            "OCSR result records are not a one-to-one ordered match for confirmed structure bindings."
        )
    for index, record in enumerate(results):
        if not isinstance(record, dict):
            errors.append("OCSR produced a malformed output record.")
            continue
        binding = bindings[index] if index < len(bindings) else None
        label = _label_key(str(record.get("cpd_id") or "")) or "unknown compound"
        errors.extend(f"{label}: {reason}" for reason in record_errors(record, binding))
    return errors


def recognition_acceptance_errors(payload: dict, bindings_payload: dict) -> list[str]:
    from .reprint_consistency import reprint_findings

    plan = recognition_inputs(bindings_payload)
    if not smiles_artifact_is_current(payload):
        return [
            "SMILES output does not match the current production artifact contract."
        ]
    if (
        payload.get("formal_acceptance_scope")
        != "proved_printed_identifier_structure_corpus"
    ):
        return [
            "SMILES output does not declare the proved original-source coverage scope."
        ]
    errors = validate_strict_smiles_results(plan.formal, smiles_records(payload))
    errors.extend(
        validate_strict_smiles_results(
            plan.supplemental, smiles_source_records(payload)
        )
    )
    for label, findings in reprint_findings(plan, payload).items():
        errors.extend(f"{label}: {reason}" for reason in findings)
    return list(dict.fromkeys(errors))
