"""One content/parameter fingerprint authority for stage and checkpoint reuse."""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

from patent_sar_extractor.artifact_io import load_json as _load_json
from patent_sar_extractor.artifact_io import write_json_atomic as _write_json
from patent_sar_extractor.contracts import (
    STEP_MANIFEST_SCHEMA,
    STEP_MANIFEST_SCHEMA_VERSION,
    artifact_identity,
    artifact_identity_matches,
    pipeline_contract_ref,
    product_ref,
    release_compatible_record,
    ruleset_ref,
)

_FILE_HASH_CACHE: dict[str, tuple[tuple[int, ...], str]] = {}


def _file_sha256(path: str) -> str:
    if not path or not os.path.isfile(path):
        return ""
    path = os.path.abspath(path)
    stat = os.stat(path)
    signature = (
        stat.st_dev,
        stat.st_ino,
        stat.st_size,
        stat.st_mtime_ns,
        stat.st_ctime_ns,
    )
    cached = _FILE_HASH_CACHE.get(path)
    if cached and cached[0] == signature:
        return cached[1]
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    value = digest.hexdigest()
    after = os.stat(path)
    if signature != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    ):
        raise ValueError(
            "Stage input changed while its content was being fingerprinted"
        )
    if len(_FILE_HASH_CACHE) >= 4096:
        _FILE_HASH_CACHE.pop(next(iter(_FILE_HASH_CACHE)))
    _FILE_HASH_CACHE[path] = signature, value
    return value


def _stable_digest(payload) -> str:
    data = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _bindings_ocsr_digest(path: str) -> str:
    payload = _load_json(path, {})
    if isinstance(payload, dict):
        from patent_sar_extractor.core.binding_records import binding_records
        from patent_sar_extractor.core.ocsr.recognition_inputs import recognition_inputs

        bindings = binding_records(payload, legacy=True)
        if "compound_catalog" in payload:
            bindings = recognition_inputs(payload).work_items
    elif isinstance(payload, list):
        bindings = payload
    else:
        bindings = []
    from patent_sar_extractor.core.ocsr.recognition_source_paths import (
        resolve_image_paths,
    )

    bindings = resolve_image_paths(
        bindings, str(Path(path).resolve().parent), attach_geometry=False
    )
    relevant = [
        {
            "cpd": item.get("cpd") or item.get("cpd_id") or item.get("compound_id"),
            "structure_id": item.get("structure_id"),
            "image_path": item.get("image_path"),
            "source_image_path": item.get("source_image_path"),
            "ocsr_image_path": item.get("ocsr_image_path"),
            "source_proof": _stable_digest(
                {
                    key: value
                    for key, value in item.items()
                    if key != "additional_sources"
                }
            ),
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
    return release_compatible_record(existing, fingerprint)


def _write_step_manifest(output_path: str, fingerprint: dict) -> None:
    _write_json(
        _manifest_path(output_path),
        {
            **artifact_identity(STEP_MANIFEST_SCHEMA, STEP_MANIFEST_SCHEMA_VERSION),
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "fingerprint": fingerprint,
        },
    )
