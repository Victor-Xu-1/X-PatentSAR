"""
PatentSAR Extractor application commands and pipeline use case.

Main chain:
  classify -> activity -> structure-page-locate -> structures -> bind -> smiles -> final -> qa
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import subprocess
import time
from pathlib import Path

from patent_sar_extractor.core.env_runner import get_python, run_in_env, run_snippet
from patent_sar_extractor.core.activity_values import has_usable_activity_values
from patent_sar_extractor.core.pipeline_rules import annotate_binding_accuracy, summarise_binding_accuracy
from patent_sar_extractor.core.runtime_env import (
    build_gpu_env,
    host_gpu_compute_capability as _host_gpu_compute_capability,
    tensorflow_cuda_caps_support_gpu as _tf_cuda_caps_support_gpu,
)
from patent_sar_extractor.application.qa_policy import compose_qa_decision
from patent_sar_extractor.artifact_io import load_json as _load_json
from patent_sar_extractor.artifact_io import write_json_atomic as _write_json
from patent_sar_extractor.core.page_classifier import classify_pdf
from patent_sar_extractor.core.structure_page_locator import locate_structure_pages
from patent_sar_extractor.integrations.llm.advisory_qa import run_advisory_qa
from patent_sar_extractor.contracts import (
    ACTIVITY_SCHEMA,
    ACTIVITY_SCHEMA_VERSION,
    BINDINGS_SCHEMA,
    BINDINGS_SCHEMA_VERSION,
    PAGE_OCR_CACHE_SCHEMA,
    PAGE_OCR_CACHE_SCHEMA_VERSION,
    PRODUCT_NAME,
    RUN_SUMMARY_SCHEMA,
    RUN_SUMMARY_SCHEMA_VERSION,
    STEP_MANIFEST_SCHEMA,
    STEP_MANIFEST_SCHEMA_VERSION,
    STRUCTURES_SCHEMA,
    STRUCTURES_SCHEMA_VERSION,
    __version__,
    artifact_identity,
    artifact_identity_matches,
    pipeline_contract_ref,
    product_ref,
    ruleset_ref,
    schema_ref,
)
from patent_sar_extractor.paths import PACKAGE_ROOT, config_files, state_dir
from patent_sar_extractor.failures import clear_failure_marker, write_failure_marker
from patent_sar_extractor.smiles_artifact import (
    build_smiles_artifact,
    smiles_artifact_is_current,
    smiles_records,
)

logger = logging.getLogger("patent_sar_extractor")

WORKING_ROOT = Path.cwd()
_FILE_HASH_CACHE: dict[str, tuple[int, int, str]] = {}
_DECIMER_TF_GPU_SAFE: bool | None = None
_ACTIVITY_TIMEOUT_BASE_SECONDS = 1800
_ACTIVITY_TIMEOUT_PER_PAGE_SECONDS = 10
_ACTIVITY_TIMEOUT_MAX_SECONDS = 10800
_STRUCTURE_WORKER_CONTRACT_VERSION = "2"
_STRUCTURE_LOCATOR_CONTRACT_VERSION = "2"


def _elapsed_since(start_time: float) -> float:
    return round(max(0.0, time.time() - start_time), 1)


def _merge_structure_chunk_metadata(patent_id: str, chunks: list[dict]) -> dict:
    """Merge per-chunk structure extraction metadata into one stable index."""
    merged_structures = []
    next_index = 0
    for chunk_idx, payload in enumerate(chunks):
        structures = payload.get("structures", []) if isinstance(payload, dict) else []
        if not isinstance(structures, list):
            continue
        for structure in structures:
            if not isinstance(structure, dict):
                continue
            row = dict(structure)
            row.setdefault("source_chunk_index", chunk_idx)
            row.setdefault("source_structure_id", row.get("structure_id"))
            row["structure_index"] = next_index
            row["structure_id"] = f"S{next_index:04d}"
            merged_structures.append(row)
            next_index += 1
    return {
        **artifact_identity(STRUCTURES_SCHEMA, STRUCTURES_SCHEMA_VERSION),
        "patent_number": patent_id,
        "total_structures": len(merged_structures),
        "structures": merged_structures,
        "chunked_extraction": True,
        "chunk_count": len(chunks),
    }


def _structure_chunk_fingerprint(
    *,
    pdf_path: str,
    dependencies: list[str] | None,
    chunk_index: int,
    chunk_pages: list[int],
    chunk_size: int,
    crop_regions: dict,
    gpu_mode: str,
) -> dict:
    return _step_fingerprint(
        "structures",
        pdf_path=pdf_path,
        dependencies=dependencies,
        params={
            "chunk_index": chunk_index,
            "chunk_pages": list(chunk_pages),
            "crop_regions": crop_regions or {},
            "gpu_mode": gpu_mode,
            "structure_chunk_size": chunk_size,
            "structure_worker_contract_version": _STRUCTURE_WORKER_CONTRACT_VERSION,
        },
    )


def _load_reusable_structure_chunk(chunk_output: str, fingerprint: dict) -> dict | None:
    metadata_path = os.path.join(chunk_output, "metadata.json")
    if not _fingerprint_matches(metadata_path, fingerprint):
        return None
    payload = _load_json(metadata_path, {})
    if not artifact_identity_matches(payload, STRUCTURES_SCHEMA, STRUCTURES_SCHEMA_VERSION):
        return None
    structures = payload.get("structures", [])
    if not isinstance(structures, list):
        return None
    return payload


def _structure_chunk_size() -> int:
    try:
        value = int(os.environ.get("PATENTSAR_STRUCTURE_CHUNK_SIZE", "10"))
    except ValueError:
        return 10
    return max(1, min(value, 20))


def _strict_gates_enabled(args) -> bool:
    env_value = str(os.environ.get("PATENTSAR_STRICT_GATES", "") or "").strip().lower()
    if env_value in {"1", "true", "yes", "on"}:
        return True
    return bool(getattr(args, "strict_gates", False))


def _file_sha256(path: str) -> str:
    if not path or not os.path.isfile(path):
        return ""
    path = os.path.abspath(path)
    stat = os.stat(path)
    cached = _FILE_HASH_CACHE.get(path)
    if cached and cached[0] == stat.st_mtime_ns and cached[1] == stat.st_size:
        return cached[2]
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    value = digest.hexdigest()
    _FILE_HASH_CACHE[path] = (stat.st_mtime_ns, stat.st_size, value)
    return value


def _stable_digest(payload) -> str:
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _bindings_ocsr_digest(path: str) -> str:
    payload = _load_json(path, {})
    if isinstance(payload, dict):
        bindings = payload.get("final_bindings")
        if not isinstance(bindings, list):
            bindings = payload.get("bindings", [])
    elif isinstance(payload, list):
        bindings = payload
    else:
        bindings = []
    relevant = [
        {
            "cpd": item.get("cpd") or item.get("cpd_id") or item.get("compound_id"),
            "structure_id": item.get("structure_id"),
            "image_path": item.get("image_path"),
            "source_image_path": item.get("source_image_path"),
            "ocsr_image_path": item.get("ocsr_image_path"),
        }
        for item in bindings
        if isinstance(item, dict)
    ]
    return _stable_digest(relevant)


def _manifest_path(output_path: str) -> str:
    return f"{output_path}.manifest.json"


RULE_VERSIONED_STEPS = {"activity", "locate", "structures", "bind", "smiles", "final"}


def _step_fingerprint(step: str, *, pdf_path: str, dependencies: list[str] | None = None, params: dict | None = None) -> dict:
    fingerprint = {
        "step": step,
        "product": product_ref(),
        "pipeline_contract": pipeline_contract_ref(),
        "pdf_sha256": _file_sha256(pdf_path),
        "dependency_sha256": {path: _file_sha256(path) for path in (dependencies or []) if path},
        "params_digest": _stable_digest(params or {}),
        "params": params or {},
    }
    if step in RULE_VERSIONED_STEPS:
        fingerprint["ruleset"] = ruleset_ref()
    return fingerprint


def _fingerprint_matches(output_path: str, fingerprint: dict) -> bool:
    if not os.path.isfile(output_path):
        return False
    manifest = _load_json(_manifest_path(output_path), {})
    if not artifact_identity_matches(manifest, STEP_MANIFEST_SCHEMA, STEP_MANIFEST_SCHEMA_VERSION):
        return False
    existing = manifest.get("fingerprint")
    return existing == fingerprint


def _write_step_manifest(output_path: str, fingerprint: dict) -> None:
    _write_json(_manifest_path(output_path), {
        **artifact_identity(STEP_MANIFEST_SCHEMA, STEP_MANIFEST_SCHEMA_VERSION),
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "fingerprint": fingerprint,
    })


def _normalize_cpd_label(value: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return ""
    if re.fullmatch(
        r"(?:claim\s*1\s+compound|claimed\s+compound|main\s+compound|single(?:ton)?\s+compound)",
        text,
        re.IGNORECASE,
    ):
        return "Claim 1 compound"
    match = re.search(
        r"(?:compound|cpd|example|实施例|化合物)\s*[-:]?\s*(\d+(?:-\d+)?[A-Z]?)",
        text,
        re.IGNORECASE,
    )
    if match:
        return f"Compound {match.group(1).upper()}"
    bare = re.fullmatch(r"(\d+(?:-\d+)?[A-Z]?)", text, re.IGNORECASE)
    if bare:
        return f"Compound {bare.group(1).upper()}"
    return text


def _expand_cpd_labels(value: str) -> list[str]:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return []
    if re.search(
        r"^(?:ref\.?\s*\d+|reference\b|vehicle\b|dmso\b|control\b|nab[-\s]?paclitaxel\b|paclitaxel\b)",
        text,
        re.IGNORECASE,
    ):
        return []

    expanded: list[str] = []
    prefix_match = re.match(r"^(?:compound|cpd|example|实施例|化合物)\s*[-:]?\s*(.+)$", text, re.IGNORECASE)
    if prefix_match and "/" in text:
        for part in prefix_match.group(1).split("/"):
            part = part.strip()
            if re.fullmatch(r"\d+(?:-\d+)?[A-Z]?", part, re.IGNORECASE):
                expanded.append(f"Compound {part.upper()}")
        if expanded:
            return list(dict.fromkeys(expanded))

    normalized = _normalize_cpd_label(text)
    return [normalized] if normalized else []


def _cpd_sort_key(value: str):
    parts = re.findall(r"\d+|\D+", value)
    return [int(p) if p.isdigit() else p.lower() for p in parts]


def _has_activity_payload(row: dict) -> bool:
    if not isinstance(row, dict):
        return False
    for bucket_name in ("activity_values", "cell_line_data"):
        bucket = row.get(bucket_name, {}) or {}
        if not isinstance(bucket, dict):
            continue
        if has_usable_activity_values(bucket):
            return True
    return False


def _extract_active_cpds(activity_payload: dict) -> list[str]:
    active = []
    seen = set()
    if not isinstance(activity_payload, dict):
        return []
    for row in activity_payload.get("rows", []):
        if not _has_activity_payload(row):
            continue
        for cpd in _expand_cpd_labels(row.get("cpd", "")):
            if cpd not in seen:
                active.append(cpd)
                seen.add(cpd)
    data_map = activity_payload.get("data", {})
    if isinstance(data_map, dict):
        for raw_cpd, values in data_map.items():
            if has_usable_activity_values(values):
                for cpd in _expand_cpd_labels(raw_cpd):
                    if cpd not in seen:
                        active.append(cpd)
                        seen.add(cpd)
    return active


def _annotate_activity_payload(path: str) -> list[str]:
    payload = _load_json(path, {})
    active_cpds = _extract_active_cpds(payload)
    if isinstance(payload, dict):
        changed = payload.get("active_cpds") != active_cpds
        payload["active_cpds"] = active_cpds
        for key, value in artifact_identity(ACTIVITY_SCHEMA, ACTIVITY_SCHEMA_VERSION).items():
            if payload.get(key) != value:
                payload[key] = value
                changed = True
        payload.setdefault("metadata", {})
        if isinstance(payload["metadata"], dict):
            if payload["metadata"].get("n_active_cpds") != len(active_cpds):
                payload["metadata"]["n_active_cpds"] = len(active_cpds)
                changed = True
        if changed:
            _write_json(path, payload)
    return active_cpds


def _activity_acceptance_errors(activity_payload: dict, active_cpds: list[str]) -> list[str]:
    if not isinstance(activity_payload, dict):
        return ["Activity extraction output is missing or malformed."]
    errors = []
    if not artifact_identity_matches(activity_payload, ACTIVITY_SCHEMA, ACTIVITY_SCHEMA_VERSION):
        errors.append("Activity output does not match the current activity schema and ruleset.")
    rows = activity_payload.get("rows", [])
    if not isinstance(rows, list) or not rows:
        errors.append("No activity rows were extracted; downstream structure binding is not allowed.")
        return errors
    active_set = set(active_cpds)
    review_cpds = [
        _normalize_cpd_label(row.get("cpd", ""))
        for row in rows
        if isinstance(row, dict)
        and row.get("needs_review")
        and _has_activity_payload(row)
        and any(cpd in active_set for cpd in _expand_cpd_labels(row.get("cpd", "")))
    ]
    if review_cpds:
        errors.append(f"Activity rows require review before binding ({review_cpds[:12]}).")
    if not active_cpds:
        errors.append("No compound with usable activity values was extracted.")
    if len(active_cpds) != len(set(active_cpds)):
        errors.append("Active compound list contains duplicate identifiers.")
    return errors


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


def _filter_bindings_by_active_cpds(bindings_payload: dict, active_cpds: list[str]) -> tuple[dict, int]:
    active_order = list(dict.fromkeys(
        _normalize_cpd_label(cpd) for cpd in active_cpds if _normalize_cpd_label(cpd)
    ))
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
        exact_matches = [b for b in exact_by_norm.get(active_cpd, []) if b.get("structure_id") not in used_structure_ids]
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
                b for b in bindings
                if str(b.get("structure_id") or "") not in used_structure_ids
                and _normalize_cpd_label(
                    b.get("cpd") or b.get("cpd_id") or b.get("compound_id") or b.get("original_cpd") or ""
                ) == active_cpd
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
            b for b in sorted(child_by_base.get(base, []), key=lambda item: _cpd_sort_key(_normalize_cpd_label(item.get("cpd", ""))))
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
        chosen["binding_rule"] = f"{chosen.get('binding_rule', 'binding')}_activity_parent_from_split_child"
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
        bindings_payload.update(artifact_identity(BINDINGS_SCHEMA, BINDINGS_SCHEMA_VERSION))
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


def _binding_acceptance_errors(bindings_payload: dict, active_cpds: list[str], locator: dict) -> list[str]:
    bindings = [
        annotate_binding_accuracy(dict(row)) if isinstance(row, dict) else {}
        for row in (bindings_payload.get("final_bindings", []) if isinstance(bindings_payload, dict) else [])
    ]
    expected = list(dict.fromkeys(
        _normalize_cpd_label(cpd) for cpd in active_cpds if _normalize_cpd_label(cpd)
    ))
    actual = [_normalize_cpd_label(row.get("cpd", "")) for row in bindings if isinstance(row, dict)]
    errors = []
    if bindings_payload.get("execution_mode") != "production_activity_led":
        errors.append("Bindings were not produced by the production activity-led pipeline.")
    if not expected:
        errors.append("No compound with extracted activity data is available for final-product binding.")
    if actual != expected:
        missing = [cpd for cpd in expected if cpd not in set(actual)]
        extra = [cpd for cpd in actual if cpd not in set(expected)]
        errors.append(f"Bindings do not match active compounds in table order (missing={missing[:10]}, extra={extra[:10]}).")
    structure_ids = [str(row.get("structure_id") or "") for row in bindings if row.get("structure_id")]
    if len(structure_ids) != len(bindings):
        errors.append("One or more active compounds do not have a bound structure image.")
    if len(set(structure_ids)) != len(structure_ids):
        errors.append("Multiple active compounds compete for the same structure image.")
    missing_images = []
    for row in bindings:
        candidate_paths = [
            str(row.get(field) or "").strip()
            for field in ("display_image_path", "source_image_path", "image_path")
        ]
        if not any(
            path and (
                os.path.isfile(path)
                or os.path.isfile(os.path.join(str(WORKING_ROOT), path))
            )
            for path in candidate_paths
        ):
            missing_images.append(_normalize_cpd_label(row.get("cpd", "")))
    if missing_images:
        errors.append(f"Confirmed structure image files are missing ({missing_images[:10]}).")
    if any(row.get("accuracy_status") != "confirmed" or row.get("fail_closed") for row in bindings):
        errors.append("One or more bindings lack strong confirmatory evidence.")
    if locator.get("reason") == "structure_table_authoritative_complete":
        table_cpds = {
            _normalize_cpd_label(cpd)
            for cpd in locator.get("structure_table_covered_cpds", [])
            if _normalize_cpd_label(cpd)
        }
        if table_cpds and not set(expected).issubset(table_cpds):
            errors.append("The detected authoritative structure table does not cover every active compound.")
        elif not table_cpds and int(locator.get("structure_table_coverage_count", 0) or 0) < len(expected):
            errors.append("The detected authoritative structure table does not cover every active compound.")
        if any(row.get("binding_rule") != "authoritative_structure_table_sequence" for row in bindings):
            errors.append("Authoritative structure table exists but non-table binding rules were used.")
    return errors


def _standalone_smiles_binding_preflight_errors(bindings_payload: dict) -> list[str]:
    if not isinstance(bindings_payload, dict):
        return ["SMILES input must be a current strict binding JSON payload."]
    errors = []
    if not artifact_identity_matches(bindings_payload, BINDINGS_SCHEMA, BINDINGS_SCHEMA_VERSION):
        errors.append("SMILES input bindings do not match the current bindings schema and ruleset.")
    if bindings_payload.get("execution_mode") != "production_activity_led":
        errors.append("SMILES input was not produced by the production activity-led binding stage.")
    bindings = bindings_payload.get("final_bindings", [])
    if not isinstance(bindings, list) or not bindings:
        errors.append("SMILES input has no final bindings to process.")
        return errors
    active_cpds = [_normalize_cpd_label(binding.get("cpd", "")) for binding in bindings if isinstance(binding, dict)]
    errors.extend(_binding_acceptance_errors(bindings_payload, active_cpds, {}))
    return errors


_AUTO_ACCEPTED_SMILES_ELEMENTS = {
    "H", "B", "C", "N", "O", "F", "Na", "Mg", "Si", "P", "S",
    "Cl", "K", "Ca", "Br", "I",
}


def _smiles_acceptance_errors(smiles_results: list[dict], bindings_payload: dict) -> list[str]:
    bindings = bindings_payload.get("final_bindings", []) if isinstance(bindings_payload, dict) else []
    bound_cpds = [_normalize_cpd_label(row.get("cpd", "")) for row in bindings]
    smile_cpds = [_normalize_cpd_label(row.get("cpd_id", "")) for row in smiles_results if isinstance(row, dict)]
    errors = []
    if smile_cpds != bound_cpds:
        errors.append("SMILES records do not map one-to-one to confirmed bindings in order.")
    expected_pairs = [
        (_normalize_cpd_label(row.get("cpd", "")), str(row.get("structure_id") or ""))
        for row in bindings
    ]
    actual_pairs = [
        (_normalize_cpd_label(row.get("cpd_id", "")), str(row.get("structure_id") or ""))
        for row in smiles_results
        if isinstance(row, dict)
    ]
    if actual_pairs != expected_pairs:
        errors.append("SMILES records are not tied to the exact confirmed structure images in order.")
    for row in smiles_results:
        if not isinstance(row, dict):
            errors.append("A SMILES output record is malformed.")
            continue
        cpd = _normalize_cpd_label(row.get("cpd_id", "")) or "unknown compound"
        suspicious = {
            element
            for element in re.findall(r"\[([A-Z][a-z]?)", str(row.get("canonical_smiles") or row.get("raw_smiles") or ""))
            if element not in _AUTO_ACCEPTED_SMILES_ELEMENTS
        }
        suspicious.update(str(element) for element in (row.get("suspicious_elements") or []) if str(element))
        if not row.get("rdkit_valid") or not row.get("canonical_smiles"):
            errors.append(f"{cpd}: no clean RDKit-valid SMILES was produced.")
        elif row.get("OCSR_quality_flag", "ok") != "ok" or suspicious:
            errors.append(f"{cpd}: OCSR result requires review (quality={row.get('OCSR_quality_flag')}, elements={sorted(suspicious)}).")
    return errors


def _smiles_results_can_be_reused(smiles_results: list[dict], bindings_payload: dict) -> tuple[bool, list[str]]:
    """A completed SMILES file is reusable only if it passes current strict gates."""
    errors = _smiles_acceptance_errors(smiles_results, bindings_payload)
    return not errors, errors


def _write_accuracy_failure_marker(output_dir: str, stage: str, errors: list[str]) -> None:
    write_failure_marker(output_dir, stage, errors)


def _load_io_config() -> dict:
    config_paths = config_files("pipeline_io.yaml")
    try:
        import yaml

        merged = {}
        for config_path in config_paths:
            if not config_path.is_file():
                continue
            with open(config_path, "r", encoding="utf-8") as f:
                loaded = yaml.safe_load(f) or {}
            if isinstance(loaded, dict):
                merged.update(loaded)
        return merged
    except ImportError:
        cfg = {}
        for config_path in config_paths:
            if not config_path.is_file():
                continue
            with open(config_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or ":" not in line:
                        continue
                    key, val = line.split(":", 1)
                    cfg[key.strip()] = val.strip().strip('"').strip("'")
        return cfg


def _gpu_env_extra(
    env_name: str = "decimer",
    extra_env: dict[str, str] | None = None,
    gpu_mode: str = "auto",
) -> dict[str, str]:
    merged_extra = dict(extra_env or {})
    if env_name in {"decimer", "smiles_engine"}:
        direct_decimer_env = env_name == "decimer"
        if gpu_mode == "force":
            merged_extra.setdefault("CUDA_VISIBLE_DEVICES", "0")
            merged_extra["PATENTSAR_DECIMER_ENABLE_GPU"] = "1"
            if direct_decimer_env:
                return build_gpu_env(
                    python_path=get_python(env_name),
                    extra_env=merged_extra,
                )
            return merged_extra
        if gpu_mode == "off" or not _decimer_tensorflow_gpu_safe():
            merged_extra["CUDA_VISIBLE_DEVICES"] = "-1"
            merged_extra["PATENTSAR_DECIMER_ENABLE_GPU"] = "0"
            merged_extra["LD_PRELOAD"] = ""
            merged_extra["LD_LIBRARY_PATH"] = ""
            merged_extra.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
            return merged_extra
        merged_extra.setdefault("CUDA_VISIBLE_DEVICES", "0")
        merged_extra["PATENTSAR_DECIMER_ENABLE_GPU"] = "1"
        if direct_decimer_env:
            return build_gpu_env(
                python_path=get_python(env_name),
                extra_env=merged_extra,
            )
        return merged_extra
    elif gpu_mode == "off":
        merged_extra["CUDA_VISIBLE_DEVICES"] = ""
    elif gpu_mode == "force":
        merged_extra.setdefault("CUDA_VISIBLE_DEVICES", "0")
    return build_gpu_env(
        python_path=get_python(env_name),
        extra_env=merged_extra,
    )


def _decimer_tensorflow_gpu_safe() -> bool:
    global _DECIMER_TF_GPU_SAFE
    if _DECIMER_TF_GPU_SAFE is not None:
        return _DECIMER_TF_GPU_SAFE
    gpu_capability = _host_gpu_compute_capability()
    if not gpu_capability:
        _DECIMER_TF_GPU_SAFE = False
        return _DECIMER_TF_GPU_SAFE
    try:
        proc = run_snippet(
            "decimer",
            (
                "import json, tensorflow as tf\n"
                "print(json.dumps(tf.sysconfig.get_build_info().get('cuda_compute_capabilities', [])))\n"
            ),
            timeout=30,
            cwd=str(WORKING_ROOT),
            env_extra={"CUDA_VISIBLE_DEVICES": ""},
        )
        caps = json.loads((proc.stdout or "[]").strip().splitlines()[-1]) if proc.returncode == 0 else []
    except Exception as exc:
        logger.warning("DECIMER TensorFlow GPU probe failed; using CPU for structure extraction: %s", exc)
        caps = []
    _DECIMER_TF_GPU_SAFE = _tf_cuda_caps_support_gpu(caps if isinstance(caps, list) else [], gpu_capability)
    if not _DECIMER_TF_GPU_SAFE:
        logger.warning(
            "DECIMER TensorFlow GPU disabled in auto mode: GPU compute capability %s is not covered by TensorFlow CUDA capabilities %s",
            gpu_capability or "unknown",
            caps or [],
        )
    return _DECIMER_TF_GPU_SAFE


def _torch_cuda_usable_for_env(env_name: str, extra_env: dict[str, str] | None = None) -> bool:
    """Return True only when this env can actually initialize torch CUDA."""
    try:
        proc = run_snippet(
            env_name,
            "import torch, sys\nsys.exit(0 if torch.cuda.is_available() else 1)\n",
            timeout=20,
            cwd=str(WORKING_ROOT),
            env_extra=build_gpu_env(
                python_path=get_python(env_name),
                extra_env=extra_env or {},
            ),
        )
        return proc.returncode == 0
    except Exception as exc:
        logger.debug("torch CUDA probe failed for %s: %s", env_name, exc)
        return False


def _activity_timeout_seconds(classification: dict) -> int:
    """Return a bounded timeout that scales with the classified activity workload."""

    activity_pages = classification.get("activity_pages", []) if isinstance(classification, dict) else []
    page_count = len(activity_pages) if isinstance(activity_pages, list) else 0
    scaled = page_count * _ACTIVITY_TIMEOUT_PER_PAGE_SECONDS
    return min(
        _ACTIVITY_TIMEOUT_MAX_SECONDS,
        max(_ACTIVITY_TIMEOUT_BASE_SECONDS, scaled),
    )


def _run_activity_rules(pdf_path: str, classification: dict, output_dir: str, include_intermediates: bool = False) -> None:
    profile = {
        "synthesis_pages": classification.get("synthesis_pages", []),
        "activity_pages": classification.get("activity_pages", []),
        "cpd_pattern": classification.get("cpd_pattern", r"Cpd[-\s]?(\d+)"),
        "cpd_prefix_pattern": classification.get("cpd_pattern", r"Cpd[-\s]?(\d+)"),
        "cpd_prefix": classification.get("cpd_prefix", "Cpd-"),
        "table_schema": {"type": classification.get("table_layout", "single")},
        "page_count": classification.get("page_count", 0),
        "ocr_cache_path": classification.get("ocr_cache_path", ""),
    }
    code = (
        "import sys\n"
        "from patent_sar_extractor.core.activity_extractor import extract\n"
        f"extract(pdf_path={pdf_path!r}, profile={profile!r}, output_dir={output_dir!r}, include_intermediates={bool(include_intermediates)!r})\n"
    )
    timeout_seconds = _activity_timeout_seconds(classification)
    logger.info(
        "Activity subprocess timeout: %ss for %s classified activity pages",
        timeout_seconds,
        len(profile["activity_pages"]),
    )
    try:
        proc = run_snippet("base", code, timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            "activity extraction timed out after "
            f"{timeout_seconds}s for {len(profile['activity_pages'])} classified activity pages"
        ) from exc
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()[:1200]
        raise RuntimeError(f"activity extraction failed: {err}")


def _save_log(log: dict, base_dir: str):
    _write_json(os.path.join(base_dir, "pipeline_summary.json"), log)


def cmd_classify(args):
    print(f"📄 [PatentSAR] classify: {args.pdf}")
    result = classify_pdf(
        args.pdf,
        args.output or os.path.join(os.path.dirname(args.pdf), "page_classification"),
        force_ocr_cache=getattr(args, "force", False),
    )
    print(f"  synthesis={len(result.get('synthesis_pages', []))}, activity={len(result.get('activity_pages', []))}")
    return result


def cmd_excerpt(args):
    from patent_sar_extractor.core.review_excerpt import create_review_excerpt_pdf

    metadata_path = args.metadata or os.path.splitext(args.output)[0] + "_metadata.json"
    meta = create_review_excerpt_pdf(args.pdf, args.output, metadata_path, dpi=args.dpi)
    print(f"✂️ [PatentSAR] excerpt={meta.get('page_count_excerpt', '?')}/{meta.get('page_count_original', '?')}")
    return meta


def cmd_activity(args):
    from patent_sar_extractor.core.activity_extractor import extract

    output_dir = args.output or os.path.join(os.path.dirname(args.pdf) or ".", "activity_output")
    os.makedirs(output_dir, exist_ok=True)
    classification_dir = os.path.join(output_dir, "page_classification")
    profile = classify_pdf(args.pdf, classification_dir, force_ocr_cache=getattr(args, "force", False))
    if args.cpd_prefix:
        profile["cpd_pattern"] = args.cpd_prefix
        profile["cpd_prefix_pattern"] = args.cpd_prefix
    vlm_options = {}
    if args.use_vlm:
        from patent_sar_extractor.integrations.llm.config import get_vlm_config
        from patent_sar_extractor.integrations.llm.vlm import call_vlm_image

        vlm_config = get_vlm_config()
        vlm_options = {
            "vlm_api_url": str(vlm_config.get("endpoint", "")),
            "vlm_api_key": str(vlm_config.get("api_key", "")),
            "vlm_model": str(vlm_config.get("model", "")),
            "vlm_call": call_vlm_image,
        }
    result = extract(
        args.pdf,
        profile,
        output_dir,
        use_vlm=args.use_vlm,
        include_intermediates=args.include_intermediates,
        **vlm_options,
    )
    activity_json = os.path.join(output_dir, "activity_data.json")
    active_cpds = _annotate_activity_payload(activity_json) if os.path.isfile(activity_json) else []
    payload = _load_json(activity_json, {}) if os.path.isfile(activity_json) else {}
    errors = _activity_acceptance_errors(payload, active_cpds)
    if errors:
        _write_accuracy_failure_marker(output_dir, "activity", errors)
        raise RuntimeError("Strict activity acceptance gate failed: " + "; ".join(errors[:8]))
    print(f"📊 [PatentSAR] activity rows={len(result.get('rows', []))}")
    return result


def cmd_smiles(args):
    script = str(PACKAGE_ROOT / "core" / "ocsr" / "run_smiles.py")
    output_json = args.output if args.output.endswith(".json") else os.path.join(args.output, "smiles_results.json")
    output_csv = output_json.replace(".json", ".csv")
    os.makedirs(os.path.dirname(output_json) or ".", exist_ok=True)
    bindings_payload = _load_json(args.bindings, {})
    preflight_errors = _standalone_smiles_binding_preflight_errors(bindings_payload)
    if preflight_errors:
        _write_accuracy_failure_marker(
            os.path.dirname(output_json) or ".",
            "binding_preflight",
            preflight_errors,
        )
        raise RuntimeError("Strict SMILES input gate failed: " + "; ".join(preflight_errors[:8]))
    smiles_args = [
        "--input", args.bindings,
        "--output", output_json,
        "--csv-output", output_csv,
        "--engine", "decimer",
        "--fallback", "",
        "--timeout", str(args.timeout),
    ]
    if args.limit:
        smiles_args.extend(["--limit", str(args.limit)])
    if args.include_intermediates:
        smiles_args.append("--include-intermediates")
    proc = run_in_env(
        "smiles_engine",
        script,
        args=smiles_args,
        timeout=7200,
        env_extra=_gpu_env_extra("smiles_engine"),
        stream_output=True,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()[:1200]
        raise RuntimeError(f"smiles failed: {err}")
    smiles_payload = _load_json(output_json, {})
    smiles_results = smiles_records(smiles_payload)
    errors = _smiles_acceptance_errors(
        smiles_results if isinstance(smiles_results, list) else [],
        bindings_payload if isinstance(bindings_payload, dict) else {"final_bindings": bindings_payload},
    )
    if errors:
        _write_accuracy_failure_marker(os.path.dirname(output_json) or ".", "smiles", errors)
        raise RuntimeError("Strict SMILES acceptance gate failed: " + "; ".join(errors[:8]))
    print(f"🧪 [PatentSAR] smiles output={output_json}")
    return {"output_json": output_json, "output_csv": output_csv}


def _production_smiles_ocr_options() -> dict:
    """Single source of truth for accepted production OCSR engines."""
    return {
        "engine": "decimer",
        "fallback": "",
    }


def cmd_validate(args):
    from patent_sar_extractor.core.cpd_validator import validate_cpd_sequence

    known = _load_json(args.known, {})
    known_set = set(known) if isinstance(known, list) else set(known.keys())
    ocr_rows = _load_json(args.ocr_rows, [])
    result = validate_cpd_sequence(ocr_rows, known_set, args.prefix)
    if args.output:
        _write_json(args.output, result)
    print(f"✅ [PatentSAR] validate corrections={len(result['corrections'])}")
    return result


def cmd_score(args):
    from patent_sar_extractor.core.confidence_scorer import score_smiles

    data = _load_json(args.smiles_json, {})
    items = smiles_records(data) if isinstance(data, dict) else (
        data if isinstance(data, list) else []
    )
    for item in items:
        smi = item.get("smiles", item.get("SMILES", ""))
        cs = score_smiles(smi)
        item["confidence"] = {
            "overall": cs.overall,
            "level": cs.level,
            "engine_consensus": cs.engine_consensus,
            "structural_plausibility": cs.structural_plausibility,
            "context_coherence": cs.context_coherence,
        }
    if args.output:
        _write_json(
            args.output,
            build_smiles_artifact(items, execution_mode="diagnostic_scored"),
        )
    print(f"📈 [PatentSAR] score items={len(items)}")
    return items


def cmd_health(args):
    from patent_sar_extractor.core.health_check import write_health_report

    output = args.output or str(state_dir() / "health_check.json")
    report = write_health_report(output, require_gpu=not args.no_gpu)
    print(f"Health: {'OK' if report.get('ok') else 'FAILED'}")
    print(f"Report: {output}")
    if not report.get("ok"):
        raise SystemExit(2)
    return report


def cmd_check_envs(args):
    from patent_sar_extractor.core.env_runner import check_all_envs

    results = check_all_envs()
    print("🔍 [PatentSAR] check-envs")
    for name, info in results.items():
        status = "✅" if info["available"] else "❌"
        print(f"  {status} {name:15s} {info.get('version') or ''}")
    return results


def cmd_qa(args):
    from patent_sar_extractor.core.qa_report import write_qa_report

    print(f"🔎 [PatentSAR] qa: {args.output}")
    result = write_qa_report(args.output, patent_id=getattr(args, "patent_id", ""))
    print(f"  {'✅ ACCEPTED' if result.get('acceptance', {}).get('ok') else '❌ STRICT ACCEPTANCE FAILED'}")
    if not result.get("acceptance", {}).get("ok") and not getattr(args, "allow_failed", False):
        raise SystemExit(2)
    return result


def cmd_run(args):
    patent_id = getattr(args, "patent_id", None) or (re.search(r"(WO\d{6,})", args.pdf).group(1) if re.search(r"(WO\d{6,})", args.pdf) else os.path.splitext(os.path.basename(args.pdf))[0])
    io_cfg = _load_io_config()
    base_dir = args.output or (
        os.path.join(io_cfg.get("output_dir", ""), patent_id)
        if io_cfg.get("output_dir")
        else str(state_dir() / "runs" / patent_id)
    )
    force = getattr(args, "force", False)
    strict_gates = _strict_gates_enabled(args)

    step_dirs = {
        "classify": os.path.join(base_dir, "page_classification"),
        "activity": os.path.join(base_dir, "activity"),
        "locate": os.path.join(base_dir, "structure_pages"),
        "structures": os.path.join(base_dir, "structures"),
        "bind": os.path.join(base_dir, "structure_bindings"),
        "smiles": os.path.join(base_dir, "smiles"),
        "final": os.path.join(base_dir, "final_results"),
    }

    print(f"{'='*65}")
    print(f"🚀 {PRODUCT_NAME} v{__version__} — {patent_id}")
    print(f"{'='*65}")
    print(f"  PDF:      {args.pdf}")
    print(f"  Output:   {base_dir}")
    print(f"  Force:    {'yes' if force else 'no (skip completed)'}")
    print()

    pipeline_log = {
        **artifact_identity(RUN_SUMMARY_SCHEMA, RUN_SUMMARY_SCHEMA_VERSION),
        "patent_id": patent_id,
        "input_pdf": args.pdf,
        "output_dir": base_dir,
        "steps": {},
        "status": "running",
        "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "main_chain": [
            "classify",
            "activity",
            "locate",
            "structures",
            "bind",
            "smiles",
            "final",
            "qa",
        ],
        "runtime": {
            "locate_workers": int(getattr(args, "locate_workers", 1) or 1),
            "bind_workers": int(getattr(args, "bind_workers", 1) or 1),
            "smiles_workers": int(getattr(args, "smiles_workers", 1) or 1),
            "gpu_mode": getattr(args, "gpu_mode", "auto"),
            "acceptance_mode": "strict_fail_closed" if strict_gates else "review_only_partial",
        },
    }

    # Stage: deterministic classification in original-PDF page coordinates.
    step = "classify"
    t0 = time.time()
    classify_json = os.path.join(step_dirs[step], "page_classification.json")
    classify_fp = _step_fingerprint(
        step,
        pdf_path=args.pdf,
        params={
            "patent_id": patent_id,
            "page_ocr_cache_schema": schema_ref(PAGE_OCR_CACHE_SCHEMA, PAGE_OCR_CACHE_SCHEMA_VERSION),
        },
    )
    if not force and _fingerprint_matches(classify_json, classify_fp):
        classification = _load_json(classify_json, {})
        print(f"  ⏭ [{step}] 已存在，跳过")
    else:
        classification = classify_pdf(args.pdf, step_dirs[step], force_ocr_cache=force)
        _write_step_manifest(classify_json, classify_fp)
    ocr_cache_path = classification.get("ocr_cache_path", os.path.join(step_dirs[step], "page_ocr_cache.json"))
    pipeline_log["steps"][step] = {
        "status": "ok",
        "elapsed_s": _elapsed_since(t0),
        "output": classify_json,
        "ocr_cache_path": ocr_cache_path,
        "synthesis_pages": len(classification.get("synthesis_pages", [])),
        "activity_pages": len(classification.get("activity_pages", [])),
        "candidate_pages": len(classification.get("candidate_pages", [])),
    }
    print(f"     ✅ synthesis={len(classification.get('synthesis_pages', []))}, activity={len(classification.get('activity_pages', []))}, candidates={len(classification.get('candidate_pages', []))}")

    # Stage: activity
    step = "activity"
    t0 = time.time()
    act_dir = step_dirs[step]
    act_json = os.path.join(act_dir, "activity_data.json")
    activity_fp = _step_fingerprint(
        step,
        pdf_path=args.pdf,
        dependencies=[classify_json],
        params={
            "include_intermediates": bool(getattr(args, "include_intermediates", False)),
            "activity_pages": classification.get("activity_pages", []),
            "ocr_cache_path": ocr_cache_path,
        },
    )
    if not force and _fingerprint_matches(act_json, activity_fp):
        print(f"  ⏭ [{step}] 已存在，跳过")
    else:
        os.makedirs(act_dir, exist_ok=True)
        _run_activity_rules(args.pdf, classification, act_dir, include_intermediates=getattr(args, "include_intermediates", False))
        _write_step_manifest(act_json, activity_fp)
    active_cpds = _annotate_activity_payload(act_json) if os.path.isfile(act_json) else []
    activity_payload = _load_json(act_json, {}) if os.path.isfile(act_json) else {}
    act_rows = len((activity_payload or {}).get("rows", []))
    pipeline_log["steps"][step] = {
        "status": "ok" if act_rows else "empty",
        "elapsed_s": _elapsed_since(t0),
        "output": act_json,
        "rows": act_rows,
        "active_cpds": len(active_cpds),
    }
    print(f"     ✅ rows={act_rows}, active_cpds={len(active_cpds)}")
    activity_errors = _activity_acceptance_errors(activity_payload, active_cpds)
    if activity_errors:
        pipeline_log["steps"][step]["status"] = "failed" if strict_gates else "warnings"
        pipeline_log["steps"][step]["acceptance_errors"] = activity_errors
        if strict_gates:
            pipeline_log["status"] = "failed_accuracy_gate"
            _save_log(pipeline_log, base_dir)
            _write_accuracy_failure_marker(base_dir, "activity", activity_errors)
            raise RuntimeError("Strict activity acceptance gate failed: " + "; ".join(activity_errors[:8]))
        print(f"     ⚠ activity strict gate warnings={len(activity_errors)}; continuing review-only partial run")

    # Stage: locate structure pages
    step = "locate"
    t0 = time.time()
    locate_json = os.path.join(step_dirs[step], "locator.json")
    locate_fp = _step_fingerprint(
        step,
        pdf_path=args.pdf,
        dependencies=[classify_json, act_json, ocr_cache_path],
        params={
            "active_cpds": active_cpds,
            "locate_workers": int(getattr(args, "locate_workers", 1) or 1),
            "structure_locator_contract_version": _STRUCTURE_LOCATOR_CONTRACT_VERSION,
        },
    )
    if not force and _fingerprint_matches(locate_json, locate_fp):
        locator = _load_json(locate_json, {})
        print(f"  ⏭ [{step}] 已存在，跳过")
    else:
        locator = locate_structure_pages(
            args.pdf,
            classification,
            active_cpds,
            locate_json,
            workers=int(getattr(args, "locate_workers", 1) or 1),
            ocr_cache_path=ocr_cache_path,
        )
        _write_step_manifest(locate_json, locate_fp)
    structure_pages = locator.get("selected_pages", [])
    crop_regions_json = os.path.join(step_dirs[step], "crop_regions.json")
    _write_json(crop_regions_json, locator.get("crop_regions", {}))
    pipeline_log["steps"][step] = {
        "status": "ok" if structure_pages else "empty",
        "elapsed_s": _elapsed_since(t0),
        "output": locate_json,
        "crop_regions": crop_regions_json,
        "candidate_pages": len(locator.get("candidate_pool", [])),
        "selected_pages": len(structure_pages),
        "unmatched_cpds": len(locator.get("unmatched_cpds", [])),
    }
    print(f"     ✅ selected_pages={len(structure_pages)}")

    # Stage: structures
    step = "structures"
    t0 = time.time()
    structures_dir = step_dirs[step]
    structures_json = os.path.join(structures_dir, "metadata.json")
    if not active_cpds:
        print(f"  ⏭ [{step}] 无活性化合物，跳过")
        _write_json(structures_json, {
            **artifact_identity(STRUCTURES_SCHEMA, STRUCTURES_SCHEMA_VERSION),
            "patent_number": patent_id,
            "total_structures": 0,
            "structures": [],
        })
        n_structures = 0
    elif not structure_pages:
        print(f"  ⏭ [{step}] 定位器未确认任何结构页，保持空结果并交由验收闸门处理")
        _write_json(structures_json, {
            **artifact_identity(STRUCTURES_SCHEMA, STRUCTURES_SCHEMA_VERSION),
            "patent_number": patent_id,
            "total_structures": 0,
            "structures": [],
            "reason": "no_locator_confirmed_pages",
        })
        n_structures = 0
    else:
        chunk_size = _structure_chunk_size()
        structures_fp = _step_fingerprint(
            step,
            pdf_path=args.pdf,
            dependencies=[locate_json, crop_regions_json],
            params={
                "structure_pages": structure_pages,
                "crop_regions": locator.get("crop_regions", {}),
                "gpu_mode": getattr(args, "gpu_mode", "auto"),
                "structure_chunk_size": chunk_size,
                "structure_worker_contract_version": _STRUCTURE_WORKER_CONTRACT_VERSION,
            },
        )
    if active_cpds and not force and _fingerprint_matches(structures_json, structures_fp):
        structures_meta = _load_json(structures_json, {})
        n_structures = int(structures_meta.get("total_structures", 0))
        print(f"  ⏭ [{step}] 已存在，跳过")
    elif active_cpds:
        os.makedirs(structures_dir, exist_ok=True)
        structure_worker_script = str(PACKAGE_ROOT / "workers" / "extract_structures.py")
        if structure_pages and len(structure_pages) > chunk_size:
            chunk_payloads = []
            chunks_dir = os.path.join(structures_dir, ".chunks")
            os.makedirs(chunks_dir, exist_ok=True)
            for chunk_index, start in enumerate(range(0, len(structure_pages), chunk_size)):
                chunk_pages = structure_pages[start:start + chunk_size]
                chunk_output = os.path.join(chunks_dir, f"chunk_{chunk_index:03d}")
                os.makedirs(chunk_output, exist_ok=True)
                chunk_fingerprint = _structure_chunk_fingerprint(
                    pdf_path=args.pdf,
                    dependencies=[locate_json, crop_regions_json],
                    chunk_index=chunk_index,
                    chunk_pages=chunk_pages,
                    chunk_size=chunk_size,
                    crop_regions=locator.get("crop_regions", {}),
                    gpu_mode=getattr(args, "gpu_mode", "auto"),
                )
                reusable_chunk = None if force else _load_reusable_structure_chunk(chunk_output, chunk_fingerprint)
                if reusable_chunk is not None:
                    print(
                        f"     ⏭ structure chunk {chunk_index + 1}/"
                        f"{(len(structure_pages) + chunk_size - 1) // chunk_size}: "
                        f"{len(chunk_pages)} pages cached",
                        flush=True,
                    )
                    chunk_payloads.append(reusable_chunk)
                    continue
                chunk_args = ["--pdf", args.pdf, "--output", chunk_output, "--pages", *[str(p) for p in chunk_pages]]
                if locator.get("crop_regions"):
                    chunk_args.extend(["--crop-regions", crop_regions_json])
                print(
                    f"     … structure chunk {chunk_index + 1}/"
                    f"{(len(structure_pages) + chunk_size - 1) // chunk_size}: "
                    f"{len(chunk_pages)} pages",
                    flush=True,
                )
                proc = run_in_env(
                    "decimer",
                    structure_worker_script,
                    args=chunk_args,
                    timeout=1800,
                    cwd=str(WORKING_ROOT),
                    env_extra=_gpu_env_extra("decimer", gpu_mode=getattr(args, "gpu_mode", "auto")),
                    stream_output=True,
                )
                if proc.returncode != 0:
                    raise RuntimeError(
                        f"structure extraction failed in chunk {chunk_index + 1} "
                        f"(pages={[p + 1 for p in chunk_pages]})"
                    )
                chunk_meta = _load_json(os.path.join(chunk_output, "metadata.json"), {})
                _write_step_manifest(os.path.join(chunk_output, "metadata.json"), chunk_fingerprint)
                chunk_payloads.append(chunk_meta)
            chunk_patent_id = ""
            for payload in chunk_payloads:
                if isinstance(payload, dict) and payload.get("patent_number"):
                    chunk_patent_id = str(payload["patent_number"])
                    break
            structures_meta = _merge_structure_chunk_metadata(
                chunk_patent_id or (args.patent_id or Path(args.pdf).stem),
                chunk_payloads,
            )
            _write_json(structures_json, structures_meta)
        else:
            structure_worker_args = [
                "--pdf",
                args.pdf,
                "--output",
                structures_dir,
                "--pages",
                *[str(p) for p in structure_pages],
            ]
            if locator.get("crop_regions"):
                structure_worker_args.extend(["--crop-regions", crop_regions_json])
            proc = run_in_env(
                "decimer",
                structure_worker_script,
                args=structure_worker_args,
                timeout=3600,
                cwd=str(WORKING_ROOT),
                env_extra=_gpu_env_extra("decimer", gpu_mode=getattr(args, "gpu_mode", "auto")),
                stream_output=True,
            )
            if proc.returncode != 0:
                raise RuntimeError("structure extraction failed")
        structures_meta = _load_json(structures_json, {})
        n_structures = int(structures_meta.get("total_structures", 0))
        if structure_pages and n_structures == 0:
            raise RuntimeError(
                "structure extraction returned 0 structures on non-empty candidate pages; "
                "please inspect DECIMER environment and page selection"
            )
        _write_step_manifest(structures_json, structures_fp)
    pipeline_log["steps"][step] = {
        "status": "ok" if n_structures else "empty",
        "elapsed_s": _elapsed_since(t0),
        "output": structures_json,
        "total": n_structures,
    }
    print(f"     ✅ total_structures={n_structures}")

    # Stage: bind
    step = "bind"
    t0 = time.time()
    bind_dir = step_dirs[step]
    bind_json = os.path.join(bind_dir, "bindings.json")
    if not active_cpds:
        print(f"  ⏭ [{step}] 无活性化合物，跳过")
        bind_payload = {"final_bindings": []}
        _save_bindings_payload(bind_json, bind_payload)
        n_bound = 0
    elif n_structures == 0:
        print(f"  ⏭ [{step}] 无结构，跳过")
        bind_payload = {"final_bindings": []}
        _save_bindings_payload(bind_json, bind_payload)
        n_bound = 0
    else:
        bind_profile = {
            "synthesis_pages": structure_pages,
            "activity_pages": classification.get("activity_pages", []),
            "cpd_pattern": classification.get("cpd_pattern", r"Cpd[-\s]?(\d+)"),
            "cpd_prefix": classification.get("cpd_prefix", "Cpd-"),
            "table_layout": classification.get("table_layout", "single"),
            "page_count": classification.get("page_count", 0),
            "structure_candidate_pages": structure_pages,
            "active_cpds": active_cpds,
            "matched_cpds": locator.get("matched_cpds", {}),
            "ocr_text_map": locator.get("ocr_text_map", {}),
            "ocr_line_map": locator.get("ocr_line_map", {}),
            "authoritative_structure_table_pages": locator.get("structure_table_pages", []),
            "authoritative_structure_table_cpds": locator.get("structure_table_covered_cpds", []),
            "bind_workers": int(getattr(args, "bind_workers", 1) or 1),
            "allow_review_bindings": not strict_gates,
            "execution_mode": "production_activity_led",
        }
        bind_fp = _step_fingerprint(
            step,
            pdf_path=args.pdf,
            dependencies=[structures_json, act_json, locate_json, ocr_cache_path],
            params={
                **bind_profile,
                "include_intermediates": bool(getattr(args, "include_intermediates", False)),
            },
        )
    reusable_bindings = (
        _load_reusable_bindings(bind_json, bind_fp, active_cpds, locator)
        if active_cpds and n_structures and not force
        else None
    )
    if reusable_bindings is not None:
        bind_payload = reusable_bindings
        _save_bindings_payload(bind_json, bind_payload)
        n_bound = len(bind_payload.get("final_bindings", []))
        print(f"  ⏭ [{step}] 已存在，跳过")
    elif active_cpds and n_structures:
        from patent_sar_extractor.core.structure_binder import bind as binder_bind

        os.makedirs(bind_dir, exist_ok=True)
        bind_payload = binder_bind(
            pdf_path=args.pdf,
            profile=bind_profile,
            output_dir=bind_dir,
            structures_path=structures_json,
            include_intermediates=getattr(args, "include_intermediates", False),
        )
        bind_payload, removed = _filter_bindings_by_active_cpds(bind_payload, active_cpds)
        bind_payload.setdefault("activity_gate", {})
        bind_payload["activity_gate"]["removed_after_bind"] = removed
        _save_bindings_payload(bind_json, bind_payload)
        _write_step_manifest(bind_json, bind_fp)
        n_bound = len(bind_payload.get("final_bindings", []))
    pipeline_log["steps"][step] = {
        "status": "ok" if n_bound else "empty",
        "elapsed_s": _elapsed_since(t0),
        "output": bind_json,
        "bound": n_bound,
    }
    print(f"     ✅ bound={n_bound}")
    binding_errors = _binding_acceptance_errors(bind_payload, active_cpds, locator)
    if binding_errors:
        pipeline_log["steps"][step]["status"] = "failed" if strict_gates else "warnings"
        pipeline_log["steps"][step]["acceptance_errors"] = binding_errors
        if strict_gates:
            pipeline_log["status"] = "failed_accuracy_gate"
            _save_log(pipeline_log, base_dir)
            _write_accuracy_failure_marker(base_dir, "bind", binding_errors)
            raise RuntimeError("Strict binding acceptance gate failed: " + "; ".join(binding_errors[:8]))
        print(f"     ⚠ binding strict gate warnings={len(binding_errors)}; continuing review-only partial run")

    # Stage: smiles
    step = "smiles"
    t0 = time.time()
    smiles_dir = step_dirs[step]
    smiles_json = os.path.join(smiles_dir, "smiles_results.json")
    if not active_cpds or n_bound == 0:
        print(f"  ⏭ [{step}] 无需 SMILES，跳过")
        _write_json(smiles_json, build_smiles_artifact([]))
        n_smiles = 0
        n_valid = 0
    smiles_fp = _step_fingerprint(
        step,
        pdf_path=args.pdf,
        params={
            **_production_smiles_ocr_options(),
            "timeout": 300,
            "no_preprocess": True,
            "smiles_workers": int(getattr(args, "smiles_workers", 1) or 1),
            "gpu_mode": getattr(args, "gpu_mode", "auto"),
            "bindings_ocsr_digest": _bindings_ocsr_digest(bind_json),
        },
    )
    reuse_existing_smiles = False
    if active_cpds and n_bound and not force and _fingerprint_matches(smiles_json, smiles_fp):
        smiles_payload = _load_json(smiles_json, {})
        smiles_results = smiles_records(smiles_payload)
        if smiles_artifact_is_current(smiles_payload):
            reuse_existing_smiles, reuse_errors = _smiles_results_can_be_reused(
                smiles_results,
                bind_payload,
            )
        else:
            reuse_existing_smiles = False
            reuse_errors = ["SMILES output does not match the current production artifact contract."]
        if reuse_existing_smiles:
            n_smiles = len(smiles_results)
            n_valid = sum(1 for r in smiles_results if r.get("rdkit_valid"))
            print(f"  ⏭ [{step}] 已存在且通过当前严格规则，跳过")
        else:
            print(f"  ↻ [{step}] 已有结果未通过当前严格规则，重跑")
            for error in reuse_errors[:3]:
                print(f"     - {error}")
    if not reuse_existing_smiles and active_cpds and n_bound:
        os.makedirs(smiles_dir, exist_ok=True)
        smiles_cache = os.path.join(smiles_dir, "smiles_cache.sqlite")
        if force and os.path.isfile(smiles_cache):
            from patent_sar_extractor.core.ocsr.smiles_cache import SmilesCache

            purged = SmilesCache(smiles_cache).purge_non_clean()
            print(f"     ♻ purged {purged} non-clean SMILES cache entries for force rerun: {smiles_cache}")
        smiles_worker_script = str(PACKAGE_ROOT / "core" / "ocsr" / "run_smiles.py")
        ocsr_options = _production_smiles_ocr_options()
        smiles_args = [
            "--input", bind_json,
            "--output", smiles_json,
            "--engine", ocsr_options["engine"],
            "--fallback", ocsr_options["fallback"],
            "--timeout", "300",
            "--cache", smiles_cache,
            "--no-preprocess",
            "--jobs", str(getattr(args, "smiles_workers", 1) or 1),
        ]
        proc = run_in_env(
            "smiles_engine",
            smiles_worker_script,
            args=smiles_args,
            timeout=7200,
            env_extra=_gpu_env_extra("smiles_engine", gpu_mode=getattr(args, "gpu_mode", "auto")),
            stream_output=True,
        )
        if proc.returncode != 0 and not os.path.isfile(smiles_json):
            err = (proc.stderr or proc.stdout or "").strip()[:1200]
            raise RuntimeError(f"smiles failed: {err}")
        smiles_payload = _load_json(smiles_json, {})
        if not smiles_artifact_is_current(smiles_payload):
            raise RuntimeError("SMILES worker returned an incompatible or diagnostic artifact.")
        smiles_results = smiles_records(smiles_payload)
        n_smiles = len(smiles_results)
        n_valid = sum(1 for r in smiles_results if r.get("rdkit_valid"))
        _write_step_manifest(smiles_json, smiles_fp)
    pipeline_log["steps"][step] = {
        "status": "ok" if n_valid or n_smiles == 0 else "warnings",
        "elapsed_s": _elapsed_since(t0),
        "output": smiles_json,
        "total": n_smiles,
        "valid": n_valid,
    }
    print(f"     ✅ valid_smiles={n_valid}/{n_smiles}")
    smiles_payload = _load_json(smiles_json, {})
    smiles_results = smiles_records(smiles_payload)
    smiles_errors = _smiles_acceptance_errors(smiles_results, bind_payload)
    if smiles_errors:
        pipeline_log["steps"][step]["status"] = "failed" if strict_gates else "warnings"
        pipeline_log["steps"][step]["acceptance_errors"] = smiles_errors
        if strict_gates:
            pipeline_log["status"] = "failed_accuracy_gate"
            _save_log(pipeline_log, base_dir)
            _write_accuracy_failure_marker(base_dir, "smiles", smiles_errors)
            raise RuntimeError("Strict SMILES acceptance gate failed: " + "; ".join(smiles_errors[:8]))
        print(f"     ⚠ SMILES strict gate warnings={len(smiles_errors)}; continuing review-only partial run")

    # Stage: final
    step = "final"
    t0 = time.time()
    final_dir = step_dirs[step]
    excel_path = os.path.join(final_dir, f"{patent_id}_final.xlsx")
    final_fp = _step_fingerprint(
        step,
        pdf_path=args.pdf,
        dependencies=[bind_json, smiles_json, act_json],
        params={"patent_id": patent_id},
    )
    if not force and _fingerprint_matches(excel_path, final_fp):
        print(f"  ⏭ [{step}] 已存在，跳过")
    else:
        os.makedirs(final_dir, exist_ok=True)
        final_worker_script = str(PACKAGE_ROOT / "workers" / "gen_final_results.py")
        final_args = [
            "--bindings", bind_json,
            "--smiles", smiles_json,
            "--output-dir", final_dir,
            "--patent", patent_id,
        ]
        if os.path.isfile(act_json):
            final_args.extend(["--activity", act_json])
        if not strict_gates:
            final_args.append("--allow-partial")
        proc = run_in_env("base", final_worker_script, args=final_args, timeout=600)
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip()[:1200]
            final_errors = [f"Final export failed strict validation or generation: {err}"]
            pipeline_log["steps"][step] = {
                "status": "failed",
                "elapsed_s": _elapsed_since(t0),
                "output": final_dir,
                "acceptance_errors": final_errors,
            }
            pipeline_log["status"] = "failed_accuracy_gate"
            _save_log(pipeline_log, base_dir)
            _write_accuracy_failure_marker(base_dir, "final_export", final_errors)
            raise RuntimeError(f"final results failed: {err}")
        _write_step_manifest(excel_path, final_fp)
    pipeline_log["steps"][step] = {
        "status": "ok",
        "elapsed_s": _elapsed_since(t0),
        "output": final_dir,
        "excel": os.path.isfile(excel_path),
        "sdf": any(Path(final_dir).glob("*.sdf")),
    }
    print("     ✅ final_results ready")

    # Stage: QA
    step = "qa"
    t0 = time.time()
    from patent_sar_extractor.core.qa_report import write_qa_report

    # QA reads the persisted run summary.  Persist the current run before the
    # gate so it never evaluates stale metadata from an earlier execution.
    pipeline_log["status"] = "qa_pending"
    _save_log(pipeline_log, base_dir)
    deterministic_qa = write_qa_report(
        base_dir,
        patent_id=patent_id,
        ignore_previous_failure_marker=True,
    )
    llm_qa = run_advisory_qa(base_dir, enabled=not getattr(args, "skip_advisory_qa", False))
    qa_decision = compose_qa_decision(deterministic_qa, llm_qa)
    combined_warnings = qa_decision["warnings"]
    qa_ok = bool(qa_decision["ok"])
    acceptance = qa_decision["acceptance"]
    pipeline_log["steps"][step] = {
        "status": "ok" if qa_ok else "failed" if not acceptance.get("ok", False) else "warnings",
        "elapsed_s": _elapsed_since(t0),
        "warnings": combined_warnings,
        "deterministic_ok": bool(deterministic_qa.get("ok")),
        "llm_advisory_status": llm_qa.get("status", "unknown"),
        "llm_advisory_assessment": llm_qa.get("assessment", "unavailable"),
        "llm_advisory_warnings": llm_qa.get("warnings", []),
        "strict_acceptance_ok": bool(acceptance.get("ok")),
        "hard_errors": acceptance.get("hard_errors", []),
    }
    print(f"     {'✅' if qa_ok else '⚠️'} warnings={len(combined_warnings)}")

    total_elapsed = sum(s.get("elapsed_s", 0) for s in pipeline_log["steps"].values())
    pipeline_log["status"] = "complete" if pipeline_log["steps"]["qa"]["status"] == "ok" else "review"
    pipeline_log["completed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    pipeline_log["total_elapsed_s"] = round(total_elapsed, 1)
    _save_log(pipeline_log, base_dir)

    print(f"\n{'='*65}")
    print(f"📊 {PRODUCT_NAME} v{__version__} Summary — {patent_id}")
    print(f"{'='*65}")
    for sn, si in pipeline_log["steps"].items():
        icon = "✅" if si.get("status") == "ok" else "⚠️" if si.get("status") in ("warnings", "partial", "empty") else "❌"
        print(f"  {icon} {sn:12s}  {si.get('elapsed_s', 0):>6.1f}s")
    print(f"{'─'*65}")
    print(f"  ⏱ Total: {total_elapsed:.1f}s")
    print(f"  📁 Output: {base_dir}")
    print(f"{'='*65}")
    if not qa_ok:
        rejection_reasons = acceptance.get("hard_errors", []) or combined_warnings
        if strict_gates:
            _write_accuracy_failure_marker(base_dir, "final_qa", rejection_reasons)
            raise RuntimeError("Strict final acceptance gate failed: " + "; ".join(rejection_reasons[:8]))
        print(f"  ⚠ Strict final acceptance failed; review-only partial run retained {len(rejection_reasons)} issues")
    if qa_ok:
        clear_failure_marker(base_dir)
    return pipeline_log
