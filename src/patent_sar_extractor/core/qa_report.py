#!/usr/bin/env python3
"""Deterministic QA report orchestration and output presentation."""

from __future__ import annotations

import json
import re
from pathlib import Path

from patent_sar_extractor.artifact_io import write_json_atomic
from patent_sar_extractor.contracts import (
    QA_REPORT_SCHEMA,
    QA_REPORT_SCHEMA_VERSION,
    artifact_identity,
    ruleset_ref,
)

from .formal_structure import FORMAL_SCOPE, SOURCE_EXECUTION_MODE
from .qa_checks import finish_qa, finish_warnings
from .qa_inputs import QAInputs, load_qa_inputs
from .qa_sources import _cpd_sort_key


def _report_fields(inputs: QAInputs) -> dict:
    qa = {
        **artifact_identity(QA_REPORT_SCHEMA, QA_REPORT_SCHEMA_VERSION),
        "patent_id": inputs.report_patent_id,
        "execution_mode": SOURCE_EXECUTION_MODE,
        "formal_acceptance_scope": FORMAL_SCOPE,
        "status": inputs.summary.get("status", "unknown"),
        "input_pdf": inputs.summary.get("input_pdf", ""),
        "page_count_input": inputs.profile.get("page_count"),
        "diagnostic_candidate_window_pages": len(
            inputs.profile.get("candidate_pages", [])
        ),
        "profile": {
            "page_count": inputs.profile.get("page_count"),
            "synthesis_pages": len(inputs.profile.get("synthesis_pages", [])),
            "activity_pages": len(inputs.profile.get("activity_pages", [])),
            "activity_page_indices": inputs.profile.get("activity_pages", []),
        },
        "structures": {"total": int(inputs.structures.get("total_structures", 0) or 0)},
        "bindings": {
            "examples": len(inputs.bind_cpds),
            "bound": len(inputs.bound_cpds),
            "missing_structure": sorted(
                inputs.bind_cpds - inputs.bound_cpds, key=_cpd_sort_key
            ),
            "detected_style": inputs.binding_style,
            "ruleset": inputs.bind_data.get("ruleset", {})
            if isinstance(inputs.bind_data, dict)
            else {},
            "expected_ruleset": ruleset_ref(),
            "identity_ok": inputs.binding_identity_ok,
            "execution_mode": inputs.bind_data.get("execution_mode", "")
            if isinstance(inputs.bind_data, dict)
            else "",
            "accuracy_summary": inputs.accuracy_summary,
            "recalculated_accuracy_summary": inputs.recalculated_accuracy_summary,
            "review_required": inputs.review_required_bindings,
            "structure_fallback": inputs.structure_fallback,
            "strict_visible_label_conflicts": inputs.strict_label_conflicts,
            "weak_visible_label_conflicts": inputs.weak_label_conflicts,
        },
        "smiles": {
            "identity_ok": inputs.smiles_identity_ok,
            "execution_mode": inputs.smiles_payload.get("execution_mode", "")
            if isinstance(inputs.smiles_payload, dict)
            else "",
            "total_records": len(inputs.smiles),
            "valid_records": len(inputs.valid_smiles_records),
            "unique_cpds": len(inputs.smiles_cpds),
            "valid_unique_cpds": len(inputs.valid_smiles_cpds),
            "missing_smiles": sorted(
                inputs.bind_cpds - inputs.smiles_cpds, key=_cpd_sort_key
            ),
            "invalid_smiles": sorted(inputs.invalid_smiles_cpds, key=_cpd_sort_key),
            "query_or_markush_smiles": sorted(
                inputs.query_smiles_cpds, key=_cpd_sort_key
            ),
            "suspicious_element_smiles": inputs.suspicious_smiles_records,
            "stereochemistry_errors": inputs.stereo_errors,
        },
        "activity": {
            "rows": len(inputs.activity_rows),
            "unique_cpds": len(inputs.activity_cpds),
            "active_order": inputs.activity_order,
            "targets": inputs.activity_targets,
            "missing_for_bound": sorted(
                inputs.bound_cpds - inputs.activity_bound_cpds, key=_cpd_sort_key
            ),
            "review_required": inputs.activity_review_rows,
            "ruleset": inputs.activity_ruleset,
            "expected_ruleset": ruleset_ref(),
            "identity_ok": inputs.activity_identity_ok,
        },
        "final_files": {
            "excel": [str(p) for p in inputs.excel_files],
            "sdf": [str(p) for p in inputs.sdf_files],
            "selected_excel": str(inputs.selected_excel)
            if inputs.selected_excel
            else "",
            "selected_sdf": str(inputs.selected_sdf) if inputs.selected_sdf else "",
            "excel_ok": inputs.final_excel_ok,
            "sdf_ok": inputs.final_sdf_ok,
        },
    }
    return qa


def build_qa_report(
    output_dir: str, patent_id: str = "", ignore_previous_failure_marker: bool = False
) -> dict:
    inputs = load_qa_inputs(output_dir, patent_id)
    qa = _report_fields(inputs)
    finish_qa(inputs, qa, ignore_previous_failure_marker)
    return finish_warnings(inputs, qa)


def write_qa_report(
    output_dir: str, patent_id: str = "", ignore_previous_failure_marker: bool = False
) -> dict:
    qa = build_qa_report(
        output_dir,
        patent_id=patent_id,
        ignore_previous_failure_marker=ignore_previous_failure_marker,
    )
    base = Path(output_dir)
    json_path = base / "final_qa_report.json"
    md_path = base / "final_qa_report.md"
    write_json_atomic(json_path, qa)

    lines = [
        "# PatentSAR Extractor QA Report",
        "",
        f"- Patent: {qa['patent_id']}",
        f"- Status: {qa['status']}",
        f"- Input pages: {qa['page_count_input']}",
        f"- Diagnostic candidate-window pages: {qa['diagnostic_candidate_window_pages']}",
        f"- Synthesis/Activity pages: {qa['profile']['synthesis_pages']} / {qa['profile']['activity_pages']}",
        f"- Structures: {qa['structures']['total']}",
        f"- Bound examples: {qa['bindings']['bound']} / {qa['bindings']['examples']}",
        f"- Valid SMILES records: {qa['smiles']['valid_records']} / {qa['smiles']['total_records']}",
        f"- Valid unique SMILES compounds: {qa['smiles']['valid_unique_cpds']} / {qa['smiles']['unique_cpds']}",
        f"- Activity rows: {qa['activity']['rows']} ({qa['activity']['unique_cpds']} compounds)",
        f"- Excel: {'OK' if qa['final_files']['excel_ok'] else 'MISSING'}",
        f"- SDF: {'OK' if qa['final_files']['sdf_ok'] else 'MISSING'}",
        f"- Strict acceptance: {'PASS' if qa['acceptance']['ok'] else 'FAIL'}",
        "",
        "## Strict Acceptance Errors",
    ]
    lines.extend([f"- {w}" for w in qa["acceptance"]["hard_errors"]] or ["- None"])
    lines.extend(
        [
            "",
            "## Activity Targets",
        ]
    )
    lines.extend([f"- {t}" for t in qa["activity"]["targets"]] or ["- None"])
    lines.extend(["", "## Warnings"])
    lines.extend([f"- {w}" for w in qa["warnings"]] or ["- None"])
    lines.extend(["", "## Missing Structure"])
    lines.extend(
        [f"- {x}" for x in qa["bindings"]["missing_structure"][:100]] or ["- None"]
    )
    lines.extend(["", "## Invalid SMILES"])
    lines.extend([f"- {x}" for x in qa["smiles"]["invalid_smiles"][:100]] or ["- None"])
    lines.extend(["", "## Query Or Markush SMILES"])
    lines.extend(
        [f"- {x}" for x in qa["smiles"]["query_or_markush_smiles"][:100]] or ["- None"]
    )
    lines.extend(["", "## Source Stereochemistry"])
    lines.extend(
        [
            f"- {x['cpd']}: {x['reason']}"
            for x in qa["smiles"]["stereochemistry_errors"][:100]
        ]
        or ["- None"]
    )
    lines.extend(["", "## Missing Activity For Bound Examples"])
    lines.extend(
        [f"- {x}" for x in qa["activity"]["missing_for_bound"][:150]] or ["- None"]
    )
    md_text = "\n".join(lines) + "\n"
    md_path.write_text(md_text, encoding="utf-8")

    slug_source = str(patent_id or qa.get("patent_id") or "").strip()
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", slug_source).strip("._")
    if slug:
        final_dir = base / "final_results"
        final_dir.mkdir(parents=True, exist_ok=True)
        patent_json_path = final_dir / f"{slug}_final_qa_report.json"
        patent_md_path = final_dir / f"{slug}_final_qa_report.md"
        write_json_atomic(patent_json_path, qa)
        patent_md_path.write_text(md_text, encoding="utf-8")
    return qa


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--patent-id", default="")
    parser.add_argument(
        "--allow-failed",
        action="store_true",
        help="Write report but return success when strict acceptance fails.",
    )
    args = parser.parse_args()
    qa = write_qa_report(args.output_dir, patent_id=args.patent_id)
    print(
        json.dumps(
            {
                "ok": qa["ok"],
                "acceptance": qa["acceptance"],
                "warnings": qa["warnings"],
            },
            ensure_ascii=False,
        )
    )
    if not qa["acceptance"]["ok"] and not args.allow_failed:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
