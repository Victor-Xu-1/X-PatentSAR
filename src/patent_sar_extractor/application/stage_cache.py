"""One content/parameter fingerprint authority for stage and checkpoint reuse."""

from __future__ import annotations

import hashlib
import json
import os
import time

from patent_sar_extractor.artifact_io import load_json as _load_json
from patent_sar_extractor.artifact_io import write_json_atomic as _write_json
from patent_sar_extractor.contracts import (
    STEP_MANIFEST_SCHEMA,
    STEP_MANIFEST_SCHEMA_VERSION,
    artifact_identity,
    artifact_identity_matches,
    pipeline_contract_ref,
    product_ref,
    ruleset_ref,
)

_FILE_HASH_CACHE: dict[str, tuple[int, int, str]] = {}


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
            "image_content": {
                field: _file_sha256(str(item.get(field) or ""))
                for field in ("image_path", "source_image_path", "ocsr_image_path")
            },
        }
        for item in bindings
        if isinstance(item, dict)
    ]
    return _stable_digest(relevant)


def _manifest_path(output_path: str) -> str:
    return f"{output_path}.manifest.json"


RULE_VERSIONED_STEPS = {"activity", "locate", "structures", "bind", "smiles", "final"}


def _step_fingerprint(
    step: str,
    *,
    pdf_path: str,
    dependencies: list[str] | None = None,
    params: dict | None = None,
) -> dict:
    fingerprint = {
        "step": step,
        "product": product_ref(),
        "pipeline_contract": pipeline_contract_ref(),
        "pdf_sha256": _file_sha256(pdf_path),
        "dependency_sha256": {
            path: _file_sha256(path) for path in (dependencies or []) if path
        },
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
    if not artifact_identity_matches(
        manifest, STEP_MANIFEST_SCHEMA, STEP_MANIFEST_SCHEMA_VERSION
    ):
        return False
    existing = manifest.get("fingerprint")
    return existing == fingerprint


def _write_step_manifest(output_path: str, fingerprint: dict) -> None:
    _write_json(
        _manifest_path(output_path),
        {
            **artifact_identity(STEP_MANIFEST_SCHEMA, STEP_MANIFEST_SCHEMA_VERSION),
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "fingerprint": fingerprint,
        },
    )
