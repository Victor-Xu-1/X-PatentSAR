"""Seal each successful batch with the sole current input-fingerprint authority."""

from __future__ import annotations

import json
from pathlib import Path

from patent_sar_extractor import contracts as core
from patent_sar_extractor.application.pipeline_io import _require_updated_worker_output
from patent_sar_extractor.application.stage_cache import _write_step_manifest
from patent_sar_extractor.application.structure_cache import (
    _structure_chunk_fingerprint,
)

MAX_INPUT_BYTES = 8 * 1024 * 1024


def read_bounded_json(path: Path):
    if any(parent.is_symlink() for parent in (path, *path.parents)):
        raise ValueError("Segmentation checkpoint input cannot follow symlinks")
    with path.open("rb") as stream:
        content = stream.read(MAX_INPUT_BYTES + 1)
    if len(content) > MAX_INPUT_BYTES:
        raise ValueError("Segmentation checkpoint input exceeds its bound")
    return json.loads(content)


def verified_input(
    pdf: str,
    root: Path,
    output: Path,
    pages: list[int],
    input_file: str,
    crop_regions: str,
) -> dict:
    expected_file = output / core.SEGMENTATION_INPUT_FINGERPRINT_FILE
    if Path(input_file) != expected_file:
        raise ValueError("Segmentation input fingerprint is not in its owned chunk")
    fingerprint = read_bounded_json(expected_file)
    params = fingerprint.get("params") if isinstance(fingerprint, dict) else None
    if not isinstance(params, dict):
        raise TypeError("Segmentation input parameters must be a dictionary")
    index, size, gpu = (
        params.get("chunk_index"),
        params.get("structure_chunk_size"),
        params.get("gpu_mode"),
    )
    if (
        type(index) is not int
        or not 0 <= index <= 9999
        or type(size) is not int
        or not 1 <= size <= 20
        or not isinstance(gpu, str)
        or gpu not in {"auto", "force", "off"}
        or output != root / ".chunks" / f"chunk_{index:03d}"
    ):
        raise ValueError("Segmentation checkpoint partition is invalid")
    locator_path = root.parent / "structure_pages/locator.json"
    regions_path = root.parent / "structure_pages/crop_regions.json"
    locator, regions = read_bounded_json(locator_path), read_bounded_json(regions_path)
    if not core.artifact_identity_matches(
        locator, core.STRUCTURE_LOCATION_SCHEMA, core.STRUCTURE_LOCATION_SCHEMA_VERSION
    ):
        raise ValueError("Segmentation locator does not have a current identity")
    selected = locator.get("selected_pages")
    if (
        not isinstance(selected, list)
        or len(selected) > 10000
        or any(type(page) is not int or not 0 <= page < 20000 for page in selected)
        or len(set(selected)) != len(selected)
        or selected[index * size : (index + 1) * size] != pages
        or not isinstance(regions, dict)
        or locator.get("crop_regions", {}) != regions
        or (crop_regions and Path(crop_regions) != regions_path)
        or (regions and not crop_regions)
    ):
        raise ValueError(
            "Segmentation input does not match its original locator partition"
        )
    expected = _structure_chunk_fingerprint(
        pdf_path=pdf,
        dependencies=[str(locator_path), str(regions_path)],
        chunk_index=index,
        chunk_pages=pages,
        chunk_size=size,
        crop_regions=regions,
        gpu_mode=gpu,
    )
    if fingerprint != expected:
        raise ValueError("Segmentation input fingerprint is stale or incompatible")
    return expected


def seal_chunk(output: Path, before, fingerprint: dict) -> None:
    path = output / "metadata.json"
    _require_updated_worker_output(path, before)
    payload = read_bounded_json(path)
    if (
        not core.artifact_identity_matches(
            payload, core.STRUCTURES_SCHEMA, core.STRUCTURES_SCHEMA_VERSION
        )
        or payload.get("failed_pages")
        or not isinstance(payload.get("structures"), list)
    ):
        raise ValueError("Segmentation output is not a successful current chunk")
    _write_step_manifest(str(path), fingerprint)
