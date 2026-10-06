"""Fail-closed source, chemistry and output gates; no artifact mutations."""

from __future__ import annotations

from pathlib import Path

from patent_sar_extractor.smiles_artifact import (
    smiles_source_records,
)

from .activity_identity import normalize_compound
from .activity_join import (
    activity_evidence_errors,
)
from .formal_structure import (
    FORMAL_SCOPE,
    SOURCE_EXECUTION_MODE,
    coverage_errors,
    proved_catalog,
)
from .qa_files import (
    _sdf_record_count,
    _worksheet_activity_value,
)
from .qa_inputs import QAInputs


def _binding_checks(inputs: QAInputs, qa: dict):
    hard_errors = []
    final_binding_order = [
        normalize_compound(binding.get("cpd", ""))
        for binding in inputs.bindings
        if normalize_compound(binding.get("cpd", ""))
    ]
    final_binding_pairs = [
        (
            normalize_compound(binding.get("cpd", "")),
            str(binding.get("structure_id") or ""),
        )
        for binding in inputs.bindings
        if normalize_compound(binding.get("cpd", ""))
    ]
    hard_errors.extend(
        activity_evidence_errors(inputs.activity, inputs.profile.get("activity_pages"))
    )
    hard_errors.extend(coverage_errors(inputs.bind_data))
    source_catalog = proved_catalog(inputs.bind_data)
    expected_order = [normalize_compound(row["cpd"]) for row in source_catalog]
    if final_binding_order != expected_order:
        hard_errors.append(
            "Confirmed bindings do not exactly cover the proved source catalog in order."
        )
    if smiles_source_records(inputs.smiles_payload):
        hard_errors.append(
            "Source-led formal recognition cannot split numbered compounds into supplemental records."
        )
    if inputs.smiles_payload.get("formal_acceptance_scope") != FORMAL_SCOPE:
        hard_errors.append(
            "SMILES output does not declare the source-led formal coverage scope."
        )
    for stage, findings in inputs.summary.get("scientific_errors", {}).items():
        if not isinstance(findings, list) or any(
            not isinstance(finding, str) for finding in findings
        ):
            raise ValueError("Malformed persisted scientific findings")
        hard_errors.extend(f"{stage}: {finding}" for finding in findings)
    if inputs.activity_cpds - inputs.bound_cpds:
        hard_errors.append(
            "Some measured printed IDs lack a proved structure association."
        )
    if not inputs.activity_identity_ok:
        hard_errors.append(
            "Activity output does not match the current activity schema and ruleset."
        )
    if not inputs.binding_identity_ok:
        hard_errors.append(
            "Binding output does not match the current bindings schema and ruleset."
        )
    if qa["bindings"]["execution_mode"] != SOURCE_EXECUTION_MODE:
        hard_errors.append(
            "Binding output was not produced by the production structure-led pipeline."
        )
    if any(
        inputs.accuracy_summary.get(field)
        != inputs.recalculated_accuracy_summary.get(field)
        for field in ("total", "confirmed", "review_required")
    ):
        hard_errors.append(
            "Binding accuracy summary is missing, stale, or inconsistent with current-rule confirmation."
        )
    if len(set(final_binding_order)) != len(final_binding_order):
        hard_errors.append("Confirmed bindings contain duplicate compound IDs.")
    structure_ids = [
        str(binding.get("structure_id") or "")
        for binding in inputs.bindings
        if binding.get("structure_id")
    ]
    if len(set(structure_ids)) != len(structure_ids):
        hard_errors.append(
            "More than one final compound is bound to the same structure image."
        )
    if inputs.review_required_bindings or int(
        inputs.accuracy_summary.get("review_required", 0) or 0
    ):
        hard_errors.append(
            "At least one final binding is not confirmed by strong evidence."
        )
    if inputs.strict_label_conflicts:
        hard_errors.append("A final binding has a strict visible-label conflict.")
    if inputs.weak_label_conflicts:
        hard_errors.append(
            "A final binding has competing visual-label evidence requiring review."
        )
    if len(inputs.bound_cpds) != len(source_catalog):
        hard_errors.append(
            "One or more proved source IDs lack a bound final structure."
        )
    if int(qa["structures"]["total"] or 0) < len(inputs.bindings):
        hard_errors.append(
            "Extracted structure count is smaller than confirmed binding count."
        )
    missing_binding_images = []
    for binding in inputs.bindings:
        candidates = [
            str(binding.get(field) or "").strip()
            for field in ("display_image_path", "source_image_path", "image_path")
        ]
        if not any(
            path and (Path(path).is_file() or (inputs.base / path).is_file())
            for path in candidates
        ):
            missing_binding_images.append(normalize_compound(binding.get("cpd", "")))
    if missing_binding_images:
        hard_errors.append(
            f"Confirmed binding images are missing for {missing_binding_images[:10]}."
        )
    return hard_errors, expected_order, final_binding_order, final_binding_pairs


def _recognition_checks(inputs: QAInputs, final_binding_pairs: list) -> list[str]:
    hard_errors = []
    smiles_pairs = [
        (
            normalize_compound(record.get("cpd_id", "")),
            str(record.get("structure_id") or ""),
        )
        for record in inputs.smiles
        if isinstance(record, dict)
    ]
    if len(inputs.valid_smiles_records) != len(inputs.bindings):
        hard_errors.append(
            "Every confirmed binding must have one clean, RDKit-valid SMILES record."
        )
    if not inputs.smiles_identity_ok:
        hard_errors.append(
            "SMILES output does not match the current production artifact contract."
        )
    if smiles_pairs != final_binding_pairs:
        hard_errors.append(
            "SMILES records do not exactly correspond to confirmed structure bindings in order."
        )
    if inputs.invalid_smiles_records:
        hard_errors.append(
            "Invalid SMILES records cannot remain in a final output set."
        )
    if inputs.valid_smiles_cpds != inputs.bound_cpds or len(
        inputs.valid_smiles_cpds
    ) != len(inputs.valid_smiles_records):
        hard_errors.append(
            "Clean SMILES compound IDs do not map one-to-one to bound compounds."
        )
    if inputs.query_smiles_records:
        hard_errors.append("Query/Markush SMILES cannot be exported as final products.")
    if inputs.suspicious_smiles_records:
        hard_errors.append(
            "SMILES with suspicious elements require fallback recognition or review."
        )
    if inputs.stereo_errors:
        hard_errors.append(
            "Source stereochemistry is missing, conflicting or unresolved for one or more model observations."
        )
    return hard_errors


def _output_checks(
    inputs: QAInputs, expected_order: list, ignore_previous_failure_marker: bool
) -> list[str]:
    hard_errors = []
    if (inputs.base / "STRICT_ACCEPTANCE_FAILED.json").is_file() and (
        not ignore_previous_failure_marker
    ):
        hard_errors.append(
            "This output directory contains a strict-acceptance failure marker from a failed run."
        )
    if inputs.workbook.get("error"):
        hard_errors.append(
            f"Final Excel could not be inspected: {inputs.workbook['error']}"
        )
    else:
        if inputs.final_order != expected_order:
            hard_errors.append(
                "Final Excel main sheet does not match the proved source-catalog order."
            )
        if (
            inputs.activity_order
            and inputs.activity_excel_order != inputs.activity_order
        ):
            hard_errors.append(
                "Final Excel activity sheet does not match activity-table row order."
            )
        for cpd in inputs.activity_order:
            expected = inputs.act_data.get(cpd, {})
            actual = inputs.activity_excel_rows.get(cpd, {})
            if any(
                (
                    str(actual.get(target, "")).strip() != str(value).strip()
                    for target, value in expected.items()
                )
            ):
                hard_errors.append(
                    f"Activity Results worksheet has missing or changed values for {cpd}."
                )
                break
            main_actual = inputs.final_rows.get(cpd, {})
            if any(
                (
                    str(_worksheet_activity_value(main_actual, target)).strip()
                    != str(value).strip()
                    for target, value in expected.items()
                )
            ):
                hard_errors.append(
                    f"Final Results worksheet has missing or changed activity values for {cpd}."
                )
                break
    if not inputs.final_excel_ok:
        hard_errors.append(
            "Final Excel is missing or is based on unbound fallback structures."
        )
    if not inputs.final_sdf_ok:
        hard_errors.append(
            "Final SDF is missing or is based on unbound fallback structures."
        )
    elif inputs.selected_sdf and _sdf_record_count(inputs.selected_sdf) != len(
        inputs.bindings
    ):
        hard_errors.append(
            "Final SDF molecule count does not match confirmed binding count."
        )
    return hard_errors


def finish_qa(inputs: QAInputs, qa: dict, ignore_previous_failure_marker: bool) -> dict:
    hard_errors, expected_order, final_binding_order, final_binding_pairs = (
        _binding_checks(inputs, qa)
    )
    hard_errors.extend(_recognition_checks(inputs, final_binding_pairs))
    hard_errors.extend(
        _output_checks(inputs, expected_order, ignore_previous_failure_marker)
    )
    review_warnings = []
    if inputs.weak_label_conflicts:
        review_warnings.append(
            "Some bindings have weak competing visual labels; retained only because stronger evidence controls."
        )
    qa["acceptance"] = {
        "mode": "strict_fail_closed",
        "ok": not hard_errors,
        "hard_errors": hard_errors,
        "review_warnings": review_warnings,
        "excel": {
            "path": str(inputs.selected_excel) if inputs.selected_excel else "",
            "sheets": {
                name: {
                    "dimension": info.get("dimension", ""),
                    "rows": len(info.get("rows", [])),
                }
                for name, info in inputs.workbook.get("sheets", {}).items()
            },
            "final_cpd_count": len(inputs.final_order),
            "activity_cpd_count": len(inputs.activity_excel_order),
        },
        "sdf_record_count": _sdf_record_count(inputs.selected_sdf)
        if inputs.selected_sdf
        else 0,
        "formal_acceptance_scope": FORMAL_SCOPE,
        "strict_coverage": {
            "expected_cpds": expected_order,
            "binding_cpds": final_binding_order,
            "smiles_cpds": [normalize_compound(r.get("cpd_id")) for r in inputs.smiles],
            "excel_cpds": inputs.final_order,
        },
    }
    return qa


def finish_warnings(inputs: QAInputs, qa: dict) -> dict:
    hard_errors = qa["acceptance"]["hard_errors"]
    warnings = []
    if qa["structures"]["total"] == 0:
        warnings.append("No structures extracted.")
    if (
        qa["bindings"]["examples"]
        and qa["bindings"]["bound"] < qa["bindings"]["examples"]
    ):
        warnings.append("Some examples are missing bound structures.")
    if qa["bindings"]["structure_fallback"]:
        warnings.append(
            "Compound IDs were not detected; structures are unbound Structure-* fallback records."
        )
    if not inputs.binding_identity_ok:
        warnings.append("Binding output uses an older or unknown schema or ruleset.")
    if qa["bindings"]["review_required"]:
        warnings.append(
            f"{len(qa['bindings']['review_required'])} bound structures lack strong patent-agnostic evidence and require review."
        )
    if qa["bindings"]["strict_visible_label_conflicts"]:
        warnings.append(
            "Some bound structures have strict visual labels for another active compound."
        )
    if (
        qa["smiles"]["total_records"]
        and qa["smiles"]["valid_records"] < qa["smiles"]["total_records"]
    ):
        warnings.append("Some SMILES are invalid or unvalidated.")
    if qa["smiles"]["query_or_markush_smiles"]:
        warnings.append(
            "Some SMILES contain dummy/query/Markush atoms and require review."
        )
    if qa["smiles"]["suspicious_element_smiles"]:
        warnings.append(
            "Some valid-looking SMILES contain suspicious elements and require fallback recognition or review."
        )
    if not qa["final_files"]["excel_ok"] or not qa["final_files"]["sdf_ok"]:
        warnings.append("Final Excel or SDF is missing.")
    for error in hard_errors:
        if error not in warnings:
            warnings.append(error)
    qa["warnings"] = warnings
    qa["ok"] = qa["acceptance"]["ok"]
    return qa
