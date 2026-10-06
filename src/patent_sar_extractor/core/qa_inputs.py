"""One immutable set of source observations for a deterministic QA pass."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from patent_sar_extractor.contracts import (
    ACTIVITY_SCHEMA,
    ACTIVITY_SCHEMA_VERSION,
    BINDINGS_SCHEMA,
    BINDINGS_SCHEMA_VERSION,
    artifact_identity_matches,
)
from patent_sar_extractor.smiles_artifact import (
    smiles_artifact_is_current,
    smiles_records,
)

from .activity_identity import normalize_compound
from .activity_join import (
    activity_for_compound,
    activity_order_and_map,
)
from .ocsr.stereo_gate import stereo_record_error
from .pipeline_rules import annotate_binding_accuracy, summarise_binding_accuracy
from .qa_files import (
    _load_json,
    _read_xlsx_values,
    _select_patent_output_file,
    _sheet_rows_by_cpd,
)
from .qa_sources import (
    _binding_accuracy_risks,
    _binding_visual_label_risks,
    _items_from_bindings,
    _suspicious_smiles_elements,
)


@dataclass(frozen=True)
class QAInputs:
    accuracy_summary: Any
    act_data: Any
    activity: Any
    activity_bound_cpds: Any
    activity_cpds: Any
    activity_excel_order: Any
    activity_excel_rows: Any
    activity_identity_ok: Any
    activity_order: Any
    activity_review_rows: Any
    activity_rows: Any
    activity_ruleset: Any
    activity_targets: Any
    base: Any
    bind_cpds: Any
    bind_data: Any
    binding_identity_ok: Any
    binding_style: Any
    bindings: Any
    bound_cpds: Any
    excel_files: Any
    final_excel_ok: Any
    final_order: Any
    final_rows: Any
    final_sdf_ok: Any
    invalid_smiles_cpds: Any
    invalid_smiles_records: Any
    profile: Any
    query_smiles_cpds: Any
    query_smiles_records: Any
    recalculated_accuracy_summary: Any
    report_patent_id: Any
    review_required_bindings: Any
    sdf_files: Any
    selected_excel: Any
    selected_sdf: Any
    smiles: Any
    smiles_cpds: Any
    smiles_identity_ok: Any
    smiles_payload: Any
    stereo_errors: Any
    strict_label_conflicts: Any
    structure_fallback: Any
    structures: Any
    summary: Any
    suspicious_smiles_records: Any
    valid_smiles_cpds: Any
    valid_smiles_records: Any
    weak_label_conflicts: Any
    workbook: Any


def load_qa_inputs(output_dir: str, patent_id: str = "") -> QAInputs:
    base = Path(output_dir)
    summary = _load_json(base / "pipeline_summary.json", {})
    profile = _load_json(base / "page_classification" / "page_classification.json", {})
    structures = _load_json(base / "structures" / "metadata.json", {})
    bind_data = _load_json(base / "structure_bindings" / "bindings.json", {})
    smiles_payload = _load_json(base / "smiles" / "smiles_results.json", {})
    smiles = smiles_records(smiles_payload)
    smiles_identity_ok = smiles_artifact_is_current(smiles_payload)
    activity = _load_json(base / "activity" / "activity_data.json", {})
    bindings = [
        annotate_binding_accuracy(dict(binding))
        if isinstance(binding, dict)
        else binding
        for binding in _items_from_bindings(bind_data)
    ]
    binding_style = (
        bind_data.get("detected_style", "") if isinstance(bind_data, dict) else ""
    )
    structure_fallback = binding_style == "structure_sequence_fallback" or (
        bindings and all(str(b.get("prefix", "")) == "Structure" for b in bindings)
    )
    bind_cpds = {
        normalize_compound(b.get("cpd", ""))
        for b in bindings
        if normalize_compound(b.get("cpd", ""))
    }
    bound_cpds = {
        normalize_compound(b.get("cpd", ""))
        for b in bindings
        if normalize_compound(b.get("cpd", ""))
        and (b.get("structure_id") or b.get("image_path"))
    }
    smiles_cpds = {
        normalize_compound(r.get("cpd_id", ""))
        for r in smiles
        if normalize_compound(r.get("cpd_id", ""))
    }
    query_smiles_records = [
        r
        for r in smiles
        if r.get("OCSR_quality_flag") == "markush_or_query"
        or r.get("has_dummy_atom")
        or r.get("has_query_atom")
    ]
    suspicious_smiles_records = [
        {
            "cpd": normalize_compound(r.get("cpd_id", "")),
            "elements": _suspicious_smiles_elements(r),
            "quality_flag": r.get("OCSR_quality_flag", ""),
        }
        for r in smiles
        if _suspicious_smiles_elements(r)
        or r.get("OCSR_quality_flag") == "suspicious_element"
    ]
    stereo_findings = [stereo_record_error(record) for record in smiles]
    valid_smiles_records = [
        r
        for index, r in enumerate(smiles)
        if r.get("rdkit_valid")
        and r not in query_smiles_records
        and (not _suspicious_smiles_elements(r))
        and (r.get("OCSR_quality_flag", "ok") == "ok")
        and (stereo_findings[index] is None)
    ]
    invalid_smiles_records = [r for r in smiles if not r.get("rdkit_valid")]
    valid_smiles_cpds = {
        normalize_compound(r.get("cpd_id", ""))
        for r in valid_smiles_records
        if normalize_compound(r.get("cpd_id", ""))
    }
    invalid_smiles_cpds = {
        normalize_compound(r.get("cpd_id", ""))
        for r in invalid_smiles_records
        if normalize_compound(r.get("cpd_id", ""))
    }
    query_smiles_cpds = {
        normalize_compound(r.get("cpd_id", ""))
        for r in query_smiles_records
        if normalize_compound(r.get("cpd_id", ""))
    }
    activity_rows = activity.get("rows", []) if isinstance(activity, dict) else []
    activity_ruleset = activity.get("ruleset", {}) if isinstance(activity, dict) else {}
    activity_identity_ok = artifact_identity_matches(
        activity, ACTIVITY_SCHEMA, ACTIVITY_SCHEMA_VERSION
    )
    binding_identity_ok = artifact_identity_matches(
        bind_data, BINDINGS_SCHEMA, BINDINGS_SCHEMA_VERSION
    )
    activity_order, act_data = activity_order_and_map(activity_rows)
    activity_cpds = set(activity_order)
    activity_review_rows = [
        normalize_compound(row.get("cpd", ""))
        for row in activity_rows
        if isinstance(row, dict)
        and row.get("needs_review")
        and (normalize_compound(row.get("cpd", "")) in activity_cpds)
    ]
    activity_targets = []
    for cpd in activity_order:
        for target in act_data.get(cpd, {}):
            if target not in activity_targets:
                activity_targets.append(target)
    activity_bound_cpds = {
        cpd for cpd in bound_cpds if activity_for_compound(act_data, cpd)
    }
    stereo_errors = [
        {"cpd": r.get("cpd_id", ""), "reason": error}
        for r, error in zip(smiles, stereo_findings)
        if error is not None
    ]
    strict_label_conflicts, weak_label_conflicts = _binding_visual_label_risks(bindings)
    review_required_bindings = _binding_accuracy_risks(bindings)
    accuracy_summary = (
        bind_data.get("accuracy_summary", {}) if isinstance(bind_data, dict) else {}
    )
    recalculated_accuracy_summary = summarise_binding_accuracy(
        [binding for binding in bindings if isinstance(binding, dict)]
    )
    report_patent_id = patent_id or summary.get("patent_id", "")
    excel_files = sorted((base / "final_results").glob("*.xlsx"))
    sdf_files = sorted((base / "final_results").glob("*.sdf"))
    nonempty_excel_files = [p for p in excel_files if p.stat().st_size > 0]
    nonempty_sdf_files = [p for p in sdf_files if p.stat().st_size > 0]
    selected_excel = _select_patent_output_file(nonempty_excel_files, report_patent_id)
    selected_sdf = _select_patent_output_file(nonempty_sdf_files, report_patent_id)
    final_excel_ok = bool(selected_excel) and (not structure_fallback)
    final_sdf_ok = bool(selected_sdf) and (not structure_fallback)
    workbook = (
        _read_xlsx_values(selected_excel)
        if selected_excel
        else {"sheets": {}, "error": "missing workbook"}
    )
    final_sheet = workbook.get("sheets", {}).get("Final Results", {})
    activity_sheet = workbook.get("sheets", {}).get("Activity Results", {})
    final_order, final_rows = _sheet_rows_by_cpd(final_sheet)
    activity_excel_order, activity_excel_rows = _sheet_rows_by_cpd(activity_sheet)
    return QAInputs(
        accuracy_summary=accuracy_summary,
        act_data=act_data,
        activity=activity,
        activity_bound_cpds=activity_bound_cpds,
        activity_cpds=activity_cpds,
        activity_excel_order=activity_excel_order,
        activity_excel_rows=activity_excel_rows,
        activity_identity_ok=activity_identity_ok,
        activity_order=activity_order,
        activity_review_rows=activity_review_rows,
        activity_rows=activity_rows,
        activity_ruleset=activity_ruleset,
        activity_targets=activity_targets,
        base=base,
        bind_cpds=bind_cpds,
        bind_data=bind_data,
        binding_identity_ok=binding_identity_ok,
        binding_style=binding_style,
        bindings=bindings,
        bound_cpds=bound_cpds,
        excel_files=excel_files,
        final_excel_ok=final_excel_ok,
        final_order=final_order,
        final_rows=final_rows,
        final_sdf_ok=final_sdf_ok,
        invalid_smiles_cpds=invalid_smiles_cpds,
        invalid_smiles_records=invalid_smiles_records,
        profile=profile,
        query_smiles_cpds=query_smiles_cpds,
        query_smiles_records=query_smiles_records,
        recalculated_accuracy_summary=recalculated_accuracy_summary,
        report_patent_id=report_patent_id,
        review_required_bindings=review_required_bindings,
        sdf_files=sdf_files,
        selected_excel=selected_excel,
        selected_sdf=selected_sdf,
        smiles=smiles,
        smiles_cpds=smiles_cpds,
        smiles_identity_ok=smiles_identity_ok,
        smiles_payload=smiles_payload,
        stereo_errors=stereo_errors,
        strict_label_conflicts=strict_label_conflicts,
        structure_fallback=structure_fallback,
        structures=structures,
        summary=summary,
        suspicious_smiles_records=suspicious_smiles_records,
        valid_smiles_cpds=valid_smiles_cpds,
        valid_smiles_records=valid_smiles_records,
        weak_label_conflicts=weak_label_conflicts,
        workbook=workbook,
    )
