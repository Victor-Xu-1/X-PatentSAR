"""binding policy: single application-layer policy authority."""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

from patent_sar_extractor.application.stage_cache import (
    _fingerprint_matches,
)
from patent_sar_extractor.artifact_io import load_json as _load_json
from patent_sar_extractor.artifact_io import write_json_atomic as _write_json
from patent_sar_extractor.contracts import (
    BINDINGS_SCHEMA,
    BINDINGS_SCHEMA_VERSION,
    artifact_identity,
    artifact_identity_matches,
)
from patent_sar_extractor.core.pipeline_rules import (
    annotate_binding_accuracy,
    summarise_binding_accuracy,
)

from .activity_policy import (
    _cpd_sort_key,
    _normalize_cpd_label,
)

logger = logging.getLogger("patent_sar_extractor")
WORKING_ROOT = Path.cwd()


def _load_bindings_from_json(path: str) -> tuple[dict, list[dict]]:
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    if isinstance(payload, dict):
        items = payload.get("final_bindings", payload.get("bindings", []))
    else:
        items = payload if isinstance(payload, list) else []
    return payload, items


def _save_bindings_payload(
    path: str,
    payload: dict,
    execution_mode: str = "production_activity_led",
) -> None:
    payload.update(artifact_identity(BINDINGS_SCHEMA, BINDINGS_SCHEMA_VERSION))
    payload["execution_mode"] = execution_mode
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                existing = json.load(f)
            if existing == payload:
                return
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            logger.debug("Existing bindings artifact could not be compared: %s", exc)
    _write_json(path, payload)


def _filter_bindings_by_active_cpds(
    bindings_payload: dict, active_cpds: list[str]
) -> tuple[dict, int]:
    active_order = list(
        dict.fromkeys(
            _normalize_cpd_label(cpd)
            for cpd in active_cpds
            if _normalize_cpd_label(cpd)
        )
    )
    if isinstance(bindings_payload, dict):
        bindings = bindings_payload.get("final_bindings")
        if not isinstance(bindings, list):
            bindings = bindings_payload.get("bindings", [])
    elif isinstance(bindings_payload, list):
        bindings = bindings_payload
    else:
        bindings = []
    exact_by_norm = {}
    child_by_base: dict[str, list[dict]] = {}
    for binding in bindings:
        norm_values = {
            _normalize_cpd_label(binding.get(field, ""))
            for field in ("cpd", "cpd_id", "compound_id", "original_cpd", "example_id")
        }
        norm_values = {norm for norm in norm_values if norm}
        if not norm_values:
            continue
        for norm in norm_values:
            exact_by_norm.setdefault(norm, []).append(binding)
            child_match = re.match(r"^Compound\s+(\d+)-([12])$", norm)
            if child_match:
                child_by_base.setdefault(child_match.group(1), []).append(binding)

    filtered = []
    used_structure_ids = set()
    for active_cpd in active_order:
        exact_matches = [
            b
            for b in exact_by_norm.get(active_cpd, [])
            if b.get("structure_id") not in used_structure_ids
        ]
        if exact_matches:
            chosen = annotate_binding_accuracy(dict(exact_matches[0]))
            if chosen.get("fail_closed"):
                continue
            chosen.setdefault("original_cpd", chosen.get("cpd", ""))
            chosen["cpd"] = active_cpd
            chosen["cpd_id"] = active_cpd
            chosen["compound_id"] = active_cpd
            chosen = annotate_binding_accuracy(chosen)
            if chosen.get("fail_closed"):
                continue
            filtered.append(chosen)
            if chosen.get("structure_id"):
                used_structure_ids.add(chosen["structure_id"])
            continue

        parent_match = re.match(r"^Compound\s+(\d+)$", active_cpd)
        if not parent_match:
            fallback_matches = [
                b
                for b in bindings
                if str(b.get("structure_id") or "") not in used_structure_ids
                and _normalize_cpd_label(
                    b.get("cpd")
                    or b.get("cpd_id")
                    or b.get("compound_id")
                    or b.get("original_cpd")
                    or ""
                )
                == active_cpd
            ]
            if fallback_matches:
                chosen = annotate_binding_accuracy(dict(fallback_matches[0]))
                if chosen.get("fail_closed"):
                    continue
                chosen.setdefault("original_cpd", chosen.get("cpd", ""))
                chosen["cpd"] = active_cpd
                chosen["cpd_id"] = active_cpd
                chosen["compound_id"] = active_cpd
                chosen = annotate_binding_accuracy(chosen)
                if chosen.get("fail_closed"):
                    continue
                filtered.append(chosen)
                if chosen.get("structure_id"):
                    used_structure_ids.add(chosen["structure_id"])
            continue
        base = parent_match.group(1)
        child_candidates = [
            b
            for b in sorted(
                child_by_base.get(base, []),
                key=lambda item: _cpd_sort_key(
                    _normalize_cpd_label(item.get("cpd", ""))
                ),
            )
            if b.get("structure_id") not in used_structure_ids
        ]
        if not child_candidates:
            continue
        chosen = annotate_binding_accuracy(dict(child_candidates[0]))
        if chosen.get("fail_closed"):
            continue
        chosen["cpd"] = active_cpd
        chosen["cpd_id"] = active_cpd
        chosen["compound_id"] = active_cpd
        chosen["binding_rule"] = (
            f"{chosen.get('binding_rule', 'binding')}_activity_parent_from_split_child"
        )
        chosen = annotate_binding_accuracy(chosen)
        if chosen.get("fail_closed"):
            continue
        filtered.append(chosen)
        if chosen.get("structure_id"):
            used_structure_ids.add(chosen["structure_id"])

    removed = len(bindings) - len(filtered)
    deduped = []
    seen = set()
    for item in filtered:
        norm = _normalize_cpd_label(item.get("cpd", ""))
        if norm in seen:
            continue
        deduped.append(item)
        seen.add(norm)
    removed += len(filtered) - len(deduped)

    if isinstance(bindings_payload, dict):
        bindings_payload["bindings"] = deduped
        bindings_payload["final_bindings"] = deduped
        bindings_payload["final_bindings_count"] = len(deduped)
        bindings_payload.update(
            artifact_identity(BINDINGS_SCHEMA, BINDINGS_SCHEMA_VERSION)
        )
        bindings_payload["accuracy_summary"] = summarise_binding_accuracy(deduped)
        bindings_payload["activity_gate"] = {
            "mode": "strict_activity_led",
            "active_cpds": active_order,
            "removed_bindings": removed,
        }
    else:
        bindings_payload = deduped
    return bindings_payload, removed


def _load_reusable_bindings(
    bind_json: str,
    fingerprint: dict,
    active_cpds: list[str],
    locator: dict,
) -> dict | None:
    if not _fingerprint_matches(bind_json, fingerprint):
        return None
    payload = _load_json(bind_json, {})
    if not artifact_identity_matches(payload, BINDINGS_SCHEMA, BINDINGS_SCHEMA_VERSION):
        return None
    payload, _removed = _filter_bindings_by_active_cpds(payload, active_cpds)
    if _binding_acceptance_errors(payload, active_cpds, locator):
        return None
    return payload


def _binding_acceptance_errors(
    bindings_payload: dict, active_cpds: list[str], locator: dict
) -> list[str]:
    bindings = [
        annotate_binding_accuracy(dict(row)) if isinstance(row, dict) else {}
        for row in (
            bindings_payload.get("final_bindings", [])
            if isinstance(bindings_payload, dict)
            else []
        )
    ]
    expected = list(
        dict.fromkeys(
            _normalize_cpd_label(cpd)
            for cpd in active_cpds
            if _normalize_cpd_label(cpd)
        )
    )
    actual = [
        _normalize_cpd_label(row.get("cpd", ""))
        for row in bindings
        if isinstance(row, dict)
    ]
    errors = []
    if bindings_payload.get("execution_mode") != "production_activity_led":
        errors.append(
            "Bindings were not produced by the production activity-led pipeline."
        )
    if not expected:
        errors.append(
            "No compound with extracted activity data is available for final-product binding."
        )
    if actual != expected:
        missing = [cpd for cpd in expected if cpd not in set(actual)]
        extra = [cpd for cpd in actual if cpd not in set(expected)]
        errors.append(
            f"Bindings do not match active compounds in table order (missing={missing[:10]}, extra={extra[:10]})."
        )
    structure_ids = [
        str(row.get("structure_id") or "")
        for row in bindings
        if row.get("structure_id")
    ]
    if len(structure_ids) != len(bindings):
        errors.append(
            "One or more active compounds do not have a bound structure image."
        )
    if len(set(structure_ids)) != len(structure_ids):
        errors.append("Multiple active compounds compete for the same structure image.")
    missing_images = []
    for row in bindings:
        candidate_paths = [
            str(row.get(field) or "").strip()
            for field in ("display_image_path", "source_image_path", "image_path")
        ]
        if not any(
            path
            and (
                os.path.isfile(path)
                or os.path.isfile(os.path.join(str(WORKING_ROOT), path))
            )
            for path in candidate_paths
        ):
            missing_images.append(_normalize_cpd_label(row.get("cpd", "")))
    if missing_images:
        errors.append(
            f"Confirmed structure image files are missing ({missing_images[:10]})."
        )
    if any(
        row.get("accuracy_status") != "confirmed" or row.get("fail_closed")
        for row in bindings
    ):
        errors.append("One or more bindings lack strong confirmatory evidence.")
    if locator.get("reason") == "structure_table_authoritative_complete":
        table_cpds = {
            _normalize_cpd_label(cpd)
            for cpd in locator.get("structure_table_covered_cpds", [])
            if _normalize_cpd_label(cpd)
        }
        if table_cpds and not set(expected).issubset(table_cpds):
            errors.append(
                "The detected authoritative structure table does not cover every active compound."
            )
        elif not table_cpds and int(
            locator.get("structure_table_coverage_count", 0) or 0
        ) < len(expected):
            errors.append(
                "The detected authoritative structure table does not cover every active compound."
            )
        if any(
            row.get("binding_rule") != "authoritative_structure_table_sequence"
            for row in bindings
        ):
            errors.append(
                "Authoritative structure table exists but non-table binding rules were used."
            )
    return errors


def _standalone_smiles_binding_preflight_errors(bindings_payload: dict) -> list[str]:
    if not isinstance(bindings_payload, dict):
        return ["SMILES input must be a current strict binding JSON payload."]
    errors = []
    if not artifact_identity_matches(
        bindings_payload, BINDINGS_SCHEMA, BINDINGS_SCHEMA_VERSION
    ):
        errors.append(
            "SMILES input bindings do not match the current bindings schema and ruleset."
        )
    if bindings_payload.get("execution_mode") != "production_activity_led":
        errors.append(
            "SMILES input was not produced by the production activity-led binding stage."
        )
    bindings = bindings_payload.get("final_bindings", [])
    if not isinstance(bindings, list) or not bindings:
        errors.append("SMILES input has no final bindings to process.")
        return errors
    active_cpds = [
        _normalize_cpd_label(binding.get("cpd", ""))
        for binding in bindings
        if isinstance(binding, dict)
    ]
    errors.extend(_binding_acceptance_errors(bindings_payload, active_cpds, {}))
    return errors
