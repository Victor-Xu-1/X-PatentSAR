#!/usr/bin/env python3
"""Final QA report generation for PatentSAR Extractor outputs."""

from __future__ import annotations

import json
import os
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from patent_sar_extractor.contracts import (
    ACTIVITY_SCHEMA,
    ACTIVITY_SCHEMA_VERSION,
    BINDINGS_SCHEMA,
    BINDINGS_SCHEMA_VERSION,
    QA_REPORT_SCHEMA,
    QA_REPORT_SCHEMA_VERSION,
    artifact_identity,
    artifact_identity_matches,
    ruleset_ref,
)
from patent_sar_extractor.core.pipeline_rules import annotate_binding_accuracy, summarise_binding_accuracy
from patent_sar_extractor.core.activity_values import has_usable_activity_values
from patent_sar_extractor.artifact_io import write_json_atomic
from patent_sar_extractor.smiles_artifact import smiles_artifact_is_current, smiles_records


def _load_json(path: Path, default: Any):
    if not path.is_file():
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _items_from_bindings(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("final_bindings", "bindings", "results", "structures"):
            if isinstance(data.get(key), list):
                return data[key]
    return []


_CPD_ID_RE = r"\d+[A-Za-z]?(?:-\d+[A-Za-z]?)?"
_CONTROL_LABEL_RE = re.compile(
    r"^(?:ref\.?\s*\d+|reference\b|vehicle\b|dmso\b|control\b|nab[-\s]?paclitaxel\b|paclitaxel\b)",
    re.IGNORECASE,
)


def _cpd_sort_key(cpd: str):
    m = re.search(r"(\d+)([A-Za-z]?)(?:-(\d+)([A-Za-z]?))?", cpd or "")
    if not m:
        return (10**9, "", 10**9, "")
    return (int(m.group(1)), m.group(2) or "", int(m.group(3) or 0), m.group(4) or "")


def _normalize_cpd_label(value: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return ""
    match = re.search(rf"(?:compound|cpd|example|实施例|化合物)\s*[-:]?\s*({_CPD_ID_RE})", text, re.IGNORECASE)
    if match:
        return f"Compound {match.group(1)}"
    return text


def _is_control_or_reference_label(value: str) -> bool:
    return bool(_CONTROL_LABEL_RE.match(re.sub(r"\s+", " ", str(value or "")).strip()))


def _expand_cpd_labels(value: str):
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return []
    prefix_match = re.match(r"^(?:compound|cpd|example|实施例|化合物)\s*[-:]?\s*(.+)$", text, re.IGNORECASE)
    if prefix_match and "/" in text:
        labels = []
        for part in prefix_match.group(1).split("/"):
            part = part.strip()
            if re.fullmatch(_CPD_ID_RE, part):
                labels.append(f"Compound {part}")
                continue
            base_match = re.match(rf"^(\d+[A-Za-z]?)-({_CPD_ID_RE})$", part)
            if base_match:
                labels.append(f"Compound {part}")
                continue
            suffix_match = re.fullmatch(r"[A-Za-z]|\d+[A-Za-z]?", part)
            first = labels[0] if labels else ""
            first_base = re.search(r"Compound\s+(\d+)", first)
            if suffix_match and first_base:
                labels.append(f"Compound {first_base.group(1)}{part}")
        if labels:
            return list(dict.fromkeys(labels))
    normalized = _normalize_cpd_label(text)
    return [normalized] if normalized else []


def _activity_map(activity_rows):
    _order, act_data = _activity_order_and_map(activity_rows)
    return act_data


def _has_activity_values(values: dict) -> bool:
    return has_usable_activity_values(values)


def _activity_order_and_map(activity_rows):
    order = []
    act_data = {}
    for row in activity_rows:
        if not isinstance(row, dict):
            continue
        values = {}
        for field in ("activity_values", "cell_line_data"):
            bucket = row.get(field, {}) or {}
            if isinstance(bucket, dict):
                values.update(bucket)
        if not _has_activity_values(values):
            continue
        for cpd in _expand_cpd_labels(row.get("cpd", "")):
            if _is_control_or_reference_label(cpd):
                continue
            if cpd not in act_data:
                order.append(cpd)
            act_data.setdefault(cpd, {}).update(values)
    return order, act_data


def _activity_for_cpd(act_data, cpd, bound_cpds):
    direct = act_data.get(cpd, {})
    if isinstance(direct, dict) and direct:
        return direct

    m = re.match(r"^Compound\s+(\d+)-([12])$", str(cpd))
    if not m:
        return {}

    base, _suffix = m.groups()
    combo_values = {}
    for combo in (f"Compound {base}-1/{base}-2", f"Compound {base}-1 和 {base}-2"):
        values = act_data.get(combo, {})
        if isinstance(values, dict):
            combo_values.update(values)
    if combo_values:
        return combo_values

    parent_key = f"Compound {base}"
    parent = act_data.get(parent_key, {})
    if parent_key not in bound_cpds and isinstance(parent, dict):
        return parent
    return {}


def _stereo_pair_duplicates(smiles_records):
    pairs = {}
    for rec in smiles_records:
        cpd = rec.get("cpd_id", "")
        m = re.match(r"^Compound\s+(\d+)-([12])$", str(cpd))
        if not m:
            continue
        pairs.setdefault(m.group(1), {})[m.group(2)] = rec

    duplicates = []
    for base, items in pairs.items():
        left = items.get("1")
        right = items.get("2")
        if not left or not right:
            continue
        if left.get("canonical_smiles") and left.get("canonical_smiles") == right.get("canonical_smiles"):
            duplicates.append(f"Compound {base}-1/{base}-2")
            continue
        if left.get("inchikey") and left.get("inchikey") == right.get("inchikey"):
            duplicates.append(f"Compound {base}-1/{base}-2")
    return sorted(duplicates, key=_cpd_sort_key)


def _binding_visual_label_risks(bindings):
    strict_sources = {"page_strict", "direct", "pdf_clip"}
    active_labels = {_normalize_cpd_label(b.get("cpd", "")) for b in bindings if isinstance(b, dict)}
    strict_conflicts = []
    weak_conflicts = []
    for binding in bindings:
        if not isinstance(binding, dict):
            continue
        cpd = _normalize_cpd_label(binding.get("cpd", ""))
        if not cpd:
            continue
        candidates = binding.get("visible_label_candidates") or []
        strict_labels = set()
        weak_labels = set()
        exact_visual_match = False
        if isinstance(candidates, list):
            for candidate in candidates:
                if not isinstance(candidate, dict):
                    continue
                label = _normalize_cpd_label(candidate.get("label", ""))
                if not label:
                    continue
                if label == cpd:
                    exact_visual_match = True
                    continue
                if candidate.get("source") in strict_sources:
                    strict_labels.add(label)
                else:
                    weak_labels.add(label)
        for label in binding.get("visible_labels") or []:
            norm = _normalize_cpd_label(label)
            if norm == cpd:
                exact_visual_match = True
            elif norm:
                weak_labels.add(norm)
        strict_labels = {label for label in strict_labels if label in active_labels}
        weak_labels = {label for label in weak_labels if label in active_labels}
        # If the crop contains the target label itself, additional small numbers
        # are usually atom/reagent annotations. Keep them review-only.
        if exact_visual_match:
            weak_labels.update(strict_labels)
            strict_labels = set()
        if (
            binding.get("binding_rule") in {"structure_table_row_order", "structure_table_row_order_inferred"}
            and re.fullmatch(r"Compound\s+\d{3}[A-Za-z]?", cpd or "")
            and all(re.fullmatch(r"Compound\s+\d{1,2}[A-Za-z]?", label or "") for label in strict_labels)
        ):
            weak_labels.update(strict_labels)
            strict_labels = set()
        target_match = re.fullmatch(r"Compound\s+(\d{3}[A-Za-z]?)", cpd or "")
        if target_match:
            target_key = target_match.group(1).upper()
            truncated = {
                label for label in strict_labels
                if (m := re.fullmatch(r"Compound\s+(\d{1,2}[A-Za-z]?)", label or ""))
                and target_key.startswith(m.group(1).upper())
            }
            if truncated:
                weak_labels.update(truncated)
                strict_labels -= truncated
        if strict_labels:
            strict_conflicts.append({
                "cpd": cpd,
                "structure_id": binding.get("structure_id"),
                "binding_rule": binding.get("binding_rule"),
                "visible_labels": sorted(strict_labels, key=_cpd_sort_key),
            })
        elif weak_labels:
            weak_conflicts.append({
                "cpd": cpd,
                "structure_id": binding.get("structure_id"),
                "binding_rule": binding.get("binding_rule"),
                "visible_labels": sorted(weak_labels, key=_cpd_sort_key),
            })
    return strict_conflicts, weak_conflicts


def _binding_accuracy_risks(bindings):
    review_required = []
    for binding in bindings:
        if not isinstance(binding, dict):
            continue
        if binding.get("accuracy_status") == "confirmed" and not binding.get("fail_closed"):
            continue
        review_required.append({
            "cpd": _normalize_cpd_label(binding.get("cpd", "")),
            "structure_id": binding.get("structure_id"),
            "binding_rule": binding.get("binding_rule"),
            "evidence_tier": binding.get("evidence_tier", "unknown"),
            "evidence_reasons": binding.get("evidence_reasons", []),
        })
    return review_required


_AUTO_ACCEPTED_ELEMENTS = {
    "H", "B", "C", "N", "O", "F", "Na", "Mg", "Si", "P", "S",
    "Cl", "K", "Ca", "Br", "I",
}


def _suspicious_smiles_elements(record: dict) -> list[str]:
    text = str(record.get("canonical_smiles") or record.get("raw_smiles") or "")
    elements = {
        element
        for element in re.findall(r"\[([A-Z][a-z]?)", text)
        if element not in _AUTO_ACCEPTED_ELEMENTS
    }
    elements.update(str(element) for element in (record.get("suspicious_elements") or []) if str(element))
    return sorted(elements)


def _excel_column_index(reference: str) -> int:
    letters = re.match(r"[A-Z]+", reference or "")
    value = 0
    for letter in (letters.group(0) if letters else ""):
        value = value * 26 + ord(letter) - ord("A") + 1
    return value - 1


def _read_xlsx_values(path: Path) -> dict:
    """Read workbook values without requiring a spreadsheet runtime."""
    ns = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    rel_ns = {"r": "http://schemas.openxmlformats.org/package/2006/relationships"}
    workbook_rel_ns = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    result = {"path": str(path), "sheets": {}, "error": ""}
    try:
        with zipfile.ZipFile(path) as archive:
            shared_strings = []
            if "xl/sharedStrings.xml" in archive.namelist():
                root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
                for item in root.findall("a:si", ns):
                    shared_strings.append("".join(t.text or "" for t in item.findall(".//a:t", ns)))

            rels_root = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
            relations = {
                rel.get("Id"): rel.get("Target", "")
                for rel in rels_root.findall("r:Relationship", rel_ns)
            }
            workbook = ET.fromstring(archive.read("xl/workbook.xml"))
            for sheet in workbook.findall("a:sheets/a:sheet", ns):
                name = sheet.get("name", "")
                target = relations.get(sheet.get(f"{{{workbook_rel_ns}}}id"), "")
                if not target:
                    continue
                if target.startswith("/"):
                    sheet_path = target.lstrip("/")
                elif target.startswith("xl/"):
                    sheet_path = target
                else:
                    sheet_path = f"xl/{target}"
                sheet_root = ET.fromstring(archive.read(sheet_path))
                dimension = sheet_root.find("a:dimension", ns)
                rows = []
                for row in sheet_root.findall("a:sheetData/a:row", ns):
                    values = []
                    for cell in row.findall("a:c", ns):
                        index = _excel_column_index(cell.get("r", ""))
                        while len(values) <= index:
                            values.append("")
                        if cell.get("t") == "inlineStr":
                            value = "".join(t.text or "" for t in cell.findall(".//a:t", ns))
                        else:
                            node = cell.find("a:v", ns)
                            value = node.text if node is not None and node.text is not None else ""
                            if cell.get("t") == "s" and value:
                                value = shared_strings[int(value)]
                        values[index] = str(value)
                    rows.append(values)
                result["sheets"][name] = {
                    "dimension": dimension.get("ref", "") if dimension is not None else "",
                    "rows": rows,
                }
    except Exception as exc:
        result["error"] = str(exc)
    return result


def _sheet_rows_by_cpd(sheet: dict) -> tuple[list[str], dict[str, dict[str, str]]]:
    rows = sheet.get("rows", []) if isinstance(sheet, dict) else []
    if not rows:
        return [], {}
    headers = [str(value or "").strip() for value in rows[0]]
    order = []
    mapped = {}
    for row in rows[1:]:
        cpd = _normalize_cpd_label(row[0] if row else "")
        if not cpd:
            continue
        order.append(cpd)
        mapped[cpd] = {
            header: str(row[index] if index < len(row) else "").strip()
            for index, header in enumerate(headers)
            if header
        }
    return order, mapped


def _worksheet_activity_value(row: dict[str, str], target: str) -> str:
    if target in row:
        return row[target]
    for header, value in row.items():
        if header.startswith(f"{target} ") or header.startswith(f"{target} ("):
            return value
    return ""


def _sdf_record_count(path: Path) -> int:
    try:
        return path.read_text(encoding="utf-8", errors="ignore").count("$$$$")
    except OSError:
        return -1


def _select_patent_output_file(files: list[Path], patent_id: str = "") -> Path | None:
    candidates = [p for p in files if p.exists() and p.stat().st_size > 0]
    if not candidates:
        return None
    patent = re.sub(r"[^A-Za-z0-9]+", "", str(patent_id or "")).upper()
    if patent:
        exact = [
            p for p in candidates
            if re.sub(r"[^A-Za-z0-9]+", "", p.stem).upper().startswith(patent)
        ]
        if exact:
            return sorted(exact, key=lambda p: (p.name.lower(), -p.stat().st_mtime))[0]
    return sorted(candidates, key=lambda p: (-p.stat().st_mtime, p.name.lower()))[0]


def build_qa_report(output_dir: str, patent_id: str = "", ignore_previous_failure_marker: bool = False) -> dict:
    base = Path(output_dir)
    summary = _load_json(base / "pipeline_summary.json", {})
    profile = _load_json(base / "page_classification" / "page_classification.json", {})
    structures = _load_json(base / "structures" / "metadata.json", {})
    bind_data = _load_json(base / "structure_bindings" / "bindings.json", {})
    smiles_payload = _load_json(base / "smiles" / "smiles_results.json", {})
    smiles = smiles_records(smiles_payload)
    smiles_identity_ok = smiles_artifact_is_current(smiles_payload)
    activity = _load_json(base / "activity" / "activity_data.json", {})
    locator = _load_json(base / "structure_pages" / "locator.json", {})

    bindings = [
        annotate_binding_accuracy(dict(binding)) if isinstance(binding, dict) else binding
        for binding in _items_from_bindings(bind_data)
    ]
    binding_style = bind_data.get("detected_style", "") if isinstance(bind_data, dict) else ""
    structure_fallback = (
        binding_style == "structure_sequence_fallback"
        or (bindings and all(str(b.get("prefix", "")) == "Structure" for b in bindings))
    )
    bind_cpds = {
        _normalize_cpd_label(b.get("cpd", ""))
        for b in bindings
        if _normalize_cpd_label(b.get("cpd", ""))
    }
    bound_cpds = {
        _normalize_cpd_label(b.get("cpd", ""))
        for b in bindings
        if _normalize_cpd_label(b.get("cpd", "")) and (b.get("structure_id") or b.get("image_path"))
    }
    smiles_cpds = {_normalize_cpd_label(r.get("cpd_id", "")) for r in smiles if _normalize_cpd_label(r.get("cpd_id", ""))}
    query_smiles_records = [
        r for r in smiles
        if r.get("OCSR_quality_flag") == "markush_or_query"
        or r.get("has_dummy_atom")
        or r.get("has_query_atom")
    ]
    suspicious_smiles_records = [
        {
            "cpd": _normalize_cpd_label(r.get("cpd_id", "")),
            "elements": _suspicious_smiles_elements(r),
            "quality_flag": r.get("OCSR_quality_flag", ""),
        }
        for r in smiles
        if _suspicious_smiles_elements(r) or r.get("OCSR_quality_flag") == "suspicious_element"
    ]
    valid_smiles_records = [
        r for r in smiles
        if r.get("rdkit_valid") and r not in query_smiles_records
        and not _suspicious_smiles_elements(r)
        and r.get("OCSR_quality_flag", "ok") == "ok"
    ]
    invalid_smiles_records = [
        r for r in smiles
        if not r.get("rdkit_valid")
    ]
    valid_smiles_cpds = {_normalize_cpd_label(r.get("cpd_id", "")) for r in valid_smiles_records if _normalize_cpd_label(r.get("cpd_id", ""))}
    invalid_smiles_cpds = {_normalize_cpd_label(r.get("cpd_id", "")) for r in invalid_smiles_records if _normalize_cpd_label(r.get("cpd_id", ""))}
    query_smiles_cpds = {_normalize_cpd_label(r.get("cpd_id", "")) for r in query_smiles_records if _normalize_cpd_label(r.get("cpd_id", ""))}
    activity_rows = activity.get("rows", []) if isinstance(activity, dict) else []
    activity_ruleset = activity.get("ruleset", {}) if isinstance(activity, dict) else {}
    activity_identity_ok = artifact_identity_matches(activity, ACTIVITY_SCHEMA, ACTIVITY_SCHEMA_VERSION)
    binding_identity_ok = artifact_identity_matches(bind_data, BINDINGS_SCHEMA, BINDINGS_SCHEMA_VERSION)
    activity_order, act_data = _activity_order_and_map(activity_rows)
    activity_cpds = set(activity_order)
    activity_review_rows = [
        _normalize_cpd_label(row.get("cpd", ""))
        for row in activity_rows
        if isinstance(row, dict)
        and row.get("needs_review")
        and _normalize_cpd_label(row.get("cpd", "")) in activity_cpds
    ]
    activity_targets = []
    for cpd in activity_order:
        for target in act_data.get(cpd, {}):
            if target not in activity_targets:
                activity_targets.append(target)
    activity_bound_cpds = {
        cpd for cpd in bound_cpds
        if _activity_for_cpd(act_data, cpd, bound_cpds)
    }
    stereo_duplicate_pairs = _stereo_pair_duplicates(smiles)
    strict_label_conflicts, weak_label_conflicts = _binding_visual_label_risks(bindings)
    review_required_bindings = _binding_accuracy_risks(bindings)
    accuracy_summary = bind_data.get("accuracy_summary", {}) if isinstance(bind_data, dict) else {}
    recalculated_accuracy_summary = summarise_binding_accuracy([
        binding for binding in bindings if isinstance(binding, dict)
    ])

    report_patent_id = patent_id or summary.get("patent_id", "")
    excel_files = sorted((base / "final_results").glob("*.xlsx"))
    sdf_files = sorted((base / "final_results").glob("*.sdf"))
    nonempty_excel_files = [p for p in excel_files if p.stat().st_size > 0]
    nonempty_sdf_files = [p for p in sdf_files if p.stat().st_size > 0]
    selected_excel = _select_patent_output_file(nonempty_excel_files, report_patent_id)
    selected_sdf = _select_patent_output_file(nonempty_sdf_files, report_patent_id)
    final_excel_ok = bool(selected_excel) and not structure_fallback
    final_sdf_ok = bool(selected_sdf) and not structure_fallback
    workbook = _read_xlsx_values(selected_excel) if selected_excel else {"sheets": {}, "error": "missing workbook"}
    final_sheet = workbook.get("sheets", {}).get("Final Results", {})
    activity_sheet = workbook.get("sheets", {}).get("Activity Results", {})
    final_order, final_rows = _sheet_rows_by_cpd(final_sheet)
    activity_excel_order, activity_excel_rows = _sheet_rows_by_cpd(activity_sheet)

    qa = {
        **artifact_identity(QA_REPORT_SCHEMA, QA_REPORT_SCHEMA_VERSION),
        "patent_id": report_patent_id,
        "status": summary.get("status", "unknown"),
        "input_pdf": summary.get("input_pdf", ""),
        "page_count_input": profile.get("page_count"),
        "diagnostic_candidate_window_pages": len(profile.get("candidate_pages", [])),
        "profile": {
            "page_count": profile.get("page_count"),
            "synthesis_pages": len(profile.get("synthesis_pages", [])),
            "activity_pages": len(profile.get("activity_pages", [])),
            "activity_page_indices": profile.get("activity_pages", []),
        },
        "structures": {
            "total": int(structures.get("total_structures", 0) or 0),
        },
        "bindings": {
            "examples": len(bind_cpds),
            "bound": len(bound_cpds),
            "missing_structure": sorted(bind_cpds - bound_cpds, key=_cpd_sort_key),
            "detected_style": binding_style,
            "ruleset": bind_data.get("ruleset", {}) if isinstance(bind_data, dict) else {},
            "expected_ruleset": ruleset_ref(),
            "identity_ok": binding_identity_ok,
            "execution_mode": bind_data.get("execution_mode", "") if isinstance(bind_data, dict) else "",
            "accuracy_summary": accuracy_summary,
            "recalculated_accuracy_summary": recalculated_accuracy_summary,
            "review_required": review_required_bindings,
            "structure_fallback": structure_fallback,
            "strict_visible_label_conflicts": strict_label_conflicts,
            "weak_visible_label_conflicts": weak_label_conflicts,
        },
        "smiles": {
            "identity_ok": smiles_identity_ok,
            "execution_mode": smiles_payload.get("execution_mode", "") if isinstance(smiles_payload, dict) else "",
            "total_records": len(smiles),
            "valid_records": len(valid_smiles_records),
            "unique_cpds": len(smiles_cpds),
            "valid_unique_cpds": len(valid_smiles_cpds),
            "missing_smiles": sorted(bind_cpds - smiles_cpds, key=_cpd_sort_key),
            "invalid_smiles": sorted(invalid_smiles_cpds, key=_cpd_sort_key),
            "query_or_markush_smiles": sorted(query_smiles_cpds, key=_cpd_sort_key),
            "suspicious_element_smiles": suspicious_smiles_records,
            "duplicate_stereo_pairs": stereo_duplicate_pairs,
        },
        "activity": {
            "rows": len(activity_rows),
            "unique_cpds": len(activity_cpds),
            "active_order": activity_order,
            "targets": activity_targets,
            "missing_for_bound": sorted(bound_cpds - activity_bound_cpds, key=_cpd_sort_key),
            "review_required": activity_review_rows,
            "ruleset": activity_ruleset,
            "expected_ruleset": ruleset_ref(),
            "identity_ok": activity_identity_ok,
        },
        "final_files": {
            "excel": [str(p) for p in excel_files],
            "sdf": [str(p) for p in sdf_files],
            "selected_excel": str(selected_excel) if selected_excel else "",
            "selected_sdf": str(selected_sdf) if selected_sdf else "",
            "excel_ok": final_excel_ok,
            "sdf_ok": final_sdf_ok,
        },
    }

    hard_errors = []
    review_warnings = []
    final_binding_order = [
        _normalize_cpd_label(binding.get("cpd", ""))
        for binding in bindings
        if _normalize_cpd_label(binding.get("cpd", ""))
    ]
    final_binding_pairs = [
        (_normalize_cpd_label(binding.get("cpd", "")), str(binding.get("structure_id") or ""))
        for binding in bindings
        if _normalize_cpd_label(binding.get("cpd", ""))
    ]
    smiles_pairs = [
        (_normalize_cpd_label(record.get("cpd_id", "")), str(record.get("structure_id") or ""))
        for record in smiles
        if isinstance(record, dict)
    ]
    if not activity_order:
        hard_errors.append("No non-empty activity compound rows are available for a deliverable.")
    if not activity_identity_ok:
        hard_errors.append("Activity output does not match the current activity schema and ruleset.")
    if activity_order and final_binding_order != activity_order:
        hard_errors.append("Confirmed bindings do not exactly cover active compounds in activity-table order.")
    if activity_review_rows:
        hard_errors.append("Activity extraction contains rows requiring review before structure binding.")
    if not binding_identity_ok:
        hard_errors.append("Binding output does not match the current bindings schema and ruleset.")
    if qa["bindings"]["execution_mode"] != "production_activity_led":
        hard_errors.append("Binding output was not produced by the production activity-led pipeline.")
    if any(
        accuracy_summary.get(field) != recalculated_accuracy_summary.get(field)
        for field in ("total", "confirmed", "review_required")
    ):
        hard_errors.append("Binding accuracy summary is missing, stale, or inconsistent with current-rule confirmation.")
    if len(set(final_binding_order)) != len(final_binding_order):
        hard_errors.append("Confirmed bindings contain duplicate compound IDs.")
    structure_ids = [str(binding.get("structure_id") or "") for binding in bindings if binding.get("structure_id")]
    if len(set(structure_ids)) != len(structure_ids):
        hard_errors.append("More than one final compound is bound to the same structure image.")
    if review_required_bindings or int(accuracy_summary.get("review_required", 0) or 0):
        hard_errors.append("At least one final binding is not confirmed by strong evidence.")
    if strict_label_conflicts:
        hard_errors.append("A final binding has a strict visible-label conflict.")
    if weak_label_conflicts:
        hard_errors.append("A final binding has competing visual-label evidence requiring review.")
    if activity_order and len(bound_cpds) != len(activity_order):
        hard_errors.append("One or more active compounds do not have a bound final structure.")
    if activity_order and int(qa["structures"]["total"] or 0) < len(bindings):
        hard_errors.append("Extracted structure count is smaller than confirmed binding count.")
    missing_binding_images = []
    for binding in bindings:
        candidates = [
            str(binding.get(field) or "").strip()
            for field in ("display_image_path", "source_image_path", "image_path")
        ]
        if not any(path and (Path(path).is_file() or (base / path).is_file()) for path in candidates):
            missing_binding_images.append(_normalize_cpd_label(binding.get("cpd", "")))
    if missing_binding_images:
        hard_errors.append(f"Confirmed binding images are missing for {missing_binding_images[:10]}.")
    if len(valid_smiles_records) != len(bindings):
        hard_errors.append("Every confirmed binding must have one clean, RDKit-valid SMILES record.")
    if not smiles_identity_ok:
        hard_errors.append("SMILES output does not match the current production artifact contract.")
    if smiles_pairs != final_binding_pairs:
        hard_errors.append("SMILES records do not exactly correspond to confirmed structure bindings in order.")
    if invalid_smiles_records:
        hard_errors.append("Invalid SMILES records cannot remain in a final output set.")
    if valid_smiles_cpds != bound_cpds or len(valid_smiles_cpds) != len(valid_smiles_records):
        hard_errors.append("Clean SMILES compound IDs do not map one-to-one to bound compounds.")
    if query_smiles_records:
        hard_errors.append("Query/Markush SMILES cannot be exported as final products.")
    if suspicious_smiles_records:
        hard_errors.append("SMILES with suspicious elements require fallback recognition or review.")
    if stereo_duplicate_pairs:
        hard_errors.append("Stereochemical pairs collapse to identical SMILES/InChIKey.")
    if locator.get("reason") == "structure_table_authoritative_complete":
        if not bindings or any(b.get("binding_rule") != "authoritative_structure_table_sequence" for b in bindings):
            hard_errors.append("An authoritative structure table was detected but not exclusively used for binding.")
    if (base / "STRICT_ACCEPTANCE_FAILED.json").is_file() and not ignore_previous_failure_marker:
        hard_errors.append("This output directory contains a strict-acceptance failure marker from a failed run.")
    if workbook.get("error"):
        hard_errors.append(f"Final Excel could not be inspected: {workbook['error']}")
    elif activity_order:
        if final_order != activity_order:
            hard_errors.append("Final Excel main sheet does not match activity-table row order.")
        if activity_excel_order != activity_order:
            hard_errors.append("Final Excel activity sheet does not match activity-table row order.")
        for cpd in activity_order:
            expected = act_data.get(cpd, {})
            actual = activity_excel_rows.get(cpd, {})
            if any(str(actual.get(target, "")).strip() != str(value).strip() for target, value in expected.items()):
                hard_errors.append(f"Activity Results worksheet has missing or changed values for {cpd}.")
                break
            main_actual = final_rows.get(cpd, {})
            if any(str(_worksheet_activity_value(main_actual, target)).strip() != str(value).strip() for target, value in expected.items()):
                hard_errors.append(f"Final Results worksheet has missing or changed activity values for {cpd}.")
                break
    if not final_excel_ok:
        hard_errors.append("Final Excel is missing or is based on unbound fallback structures.")
    if not final_sdf_ok:
        hard_errors.append("Final SDF is missing or is based on unbound fallback structures.")
    elif selected_sdf and _sdf_record_count(selected_sdf) != len(bindings):
        hard_errors.append("Final SDF molecule count does not match confirmed binding count.")
    if weak_label_conflicts:
        review_warnings.append("Some bindings have weak competing visual labels; retained only because stronger evidence controls.")
    qa["acceptance"] = {
        "mode": "strict_fail_closed",
        "ok": not hard_errors,
        "hard_errors": hard_errors,
        "review_warnings": review_warnings,
        "excel": {
            "path": str(selected_excel) if selected_excel else "",
            "sheets": {
                name: {"dimension": info.get("dimension", ""), "rows": len(info.get("rows", []))}
                for name, info in workbook.get("sheets", {}).items()
            },
            "final_cpd_count": len(final_order),
            "activity_cpd_count": len(activity_excel_order),
        },
        "sdf_record_count": _sdf_record_count(selected_sdf) if selected_sdf else 0,
    }

    warnings = []
    if qa["structures"]["total"] == 0:
        warnings.append("No structures extracted.")
    if qa["bindings"]["examples"] and qa["bindings"]["bound"] < qa["bindings"]["examples"]:
        warnings.append("Some examples are missing bound structures.")
    if qa["bindings"]["structure_fallback"]:
        warnings.append("Compound IDs were not detected; structures are unbound Structure-* fallback records.")
    if not binding_identity_ok:
        warnings.append("Binding output uses an older or unknown schema or ruleset.")
    if qa["bindings"]["review_required"]:
        warnings.append(
            f"{len(qa['bindings']['review_required'])} bound structures lack strong patent-agnostic evidence and require review."
        )
    if qa["bindings"]["strict_visible_label_conflicts"]:
        warnings.append("Some bound structures have strict visual labels for another active compound.")
    if qa["smiles"]["total_records"] and qa["smiles"]["valid_records"] < qa["smiles"]["total_records"]:
        warnings.append("Some SMILES are invalid or unvalidated.")
    if qa["smiles"]["query_or_markush_smiles"]:
        warnings.append("Some SMILES contain dummy/query/Markush atoms and require review.")
    if qa["smiles"]["suspicious_element_smiles"]:
        warnings.append("Some valid-looking SMILES contain suspicious elements and require fallback recognition or review.")
    if qa["smiles"]["duplicate_stereo_pairs"]:
        warnings.append("Some N-1/N-2 stereochemical pairs have identical SMILES/InChIKey.")
    if qa["activity"]["rows"] == 0:
        warnings.append("No activity rows extracted.")
    elif qa["activity"]["missing_for_bound"]:
        warnings.append("Some bound examples have no activity rows.")
    if not qa["final_files"]["excel_ok"] or not qa["final_files"]["sdf_ok"]:
        warnings.append("Final Excel or SDF is missing.")
    for error in hard_errors:
        if error not in warnings:
            warnings.append(error)
    qa["warnings"] = warnings
    qa["ok"] = qa["acceptance"]["ok"]
    return qa


def write_qa_report(output_dir: str, patent_id: str = "", ignore_previous_failure_marker: bool = False) -> dict:
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
    lines.extend([
        "",
        "## Activity Targets",
    ])
    lines.extend([f"- {t}" for t in qa["activity"]["targets"]] or ["- None"])
    lines.extend(["", "## Warnings"])
    lines.extend([f"- {w}" for w in qa["warnings"]] or ["- None"])
    lines.extend(["", "## Missing Structure"])
    lines.extend([f"- {x}" for x in qa["bindings"]["missing_structure"][:100]] or ["- None"])
    lines.extend(["", "## Invalid SMILES"])
    lines.extend([f"- {x}" for x in qa["smiles"]["invalid_smiles"][:100]] or ["- None"])
    lines.extend(["", "## Query Or Markush SMILES"])
    lines.extend([f"- {x}" for x in qa["smiles"]["query_or_markush_smiles"][:100]] or ["- None"])
    lines.extend(["", "## Duplicate Stereo Pairs"])
    lines.extend([f"- {x}" for x in qa["smiles"]["duplicate_stereo_pairs"][:100]] or ["- None"])
    lines.extend(["", "## Missing Activity For Bound Examples"])
    lines.extend([f"- {x}" for x in qa["activity"]["missing_for_bound"][:150]] or ["- None"])
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
    parser.add_argument("--allow-failed", action="store_true", help="Write report but return success when strict acceptance fails.")
    args = parser.parse_args()
    qa = write_qa_report(args.output_dir, patent_id=args.patent_id)
    print(json.dumps({"ok": qa["ok"], "acceptance": qa["acceptance"], "warnings": qa["warnings"]}, ensure_ascii=False))
    if not qa["acceptance"]["ok"] and not args.allow_failed:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
