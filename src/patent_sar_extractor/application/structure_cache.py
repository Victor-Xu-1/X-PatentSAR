"""structure cache: single application-layer policy authority."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from patent_sar_extractor.application.stage_cache import (
    _fingerprint_matches,
    _step_fingerprint,
)
from patent_sar_extractor.artifact_io import load_json as _load_json
from patent_sar_extractor.contracts import (
    STRUCTURE_WORKER_VERSION as _STRUCTURE_WORKER_CONTRACT_VERSION,
)
from patent_sar_extractor.contracts import (
    STRUCTURES_SCHEMA,
    STRUCTURES_SCHEMA_VERSION,
    artifact_identity,
    artifact_identity_matches,
)

logger = logging.getLogger("patent_sar_extractor")
WORKING_ROOT = Path.cwd()


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
    if not artifact_identity_matches(
        payload, STRUCTURES_SCHEMA, STRUCTURES_SCHEMA_VERSION
    ):
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
