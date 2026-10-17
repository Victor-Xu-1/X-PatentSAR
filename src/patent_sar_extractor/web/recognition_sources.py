"""Current original ownership and small QC frames for saved source completion."""

from __future__ import annotations

import hashlib
import os
import threading
from functools import lru_cache
from pathlib import Path

from patent_sar_extractor.core.ocsr.recognition_inputs import ordered_source_results
from patent_sar_extractor.core.pipeline_rules import _label_key
from patent_sar_extractor.smiles_artifact import smiles_reprint_records

from .compound_catalog import read_compound_catalog
from .errors import WebError
from .files import SafeFiles, records
from .storage import encode

MAX_COMPLETION_BYTES = 16 * 1024 * 1024
_index_lock = threading.Lock()
_SOURCE_FILES = ("structure_bindings/bindings.json", "structures/metadata.json")
_FRAME_FIELDS = (
    "cpd",
    "compound_id",
    "structure_id",
    "source_structure_id",
    "page_no",
    "bbox_pdf",
    "struct_x0",
    "struct_y0",
    "struct_x1",
    "struct_y1",
    "exact_caption_evidence",
    "_ocsr_source_geometry",
    "image_path",
)


def source_revision(project: dict) -> tuple:
    files = SafeFiles(Path(project["run_root"]))
    result = []
    for path in _SOURCE_FILES:
        with files.open(path, max_bytes=64 * 1024 * 1024) as stream:
            info = os.fstat(stream.fileno())
        result.append(
            (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
        )
    return tuple(result)


def _frame(source: dict, *, additional: bool = True) -> dict:
    if source.get("image_path") is not None and not isinstance(
        source["image_path"], str
    ):
        raise WebError(
            422, "invalid_source_image", "Original source image path is invalid."
        )
    result = {field: source[field] for field in _FRAME_FIELDS if field in source}
    if additional:
        result["additional_sources"] = [
            _frame(item, additional=False)
            for item in source.get("additional_sources", [])
        ]
    return result


@lru_cache(maxsize=2)
def _source_index(root: str, revision: tuple) -> dict:
    files = SafeFiles(Path(root))
    catalog, _ = read_compound_catalog(
        files.json(_SOURCE_FILES[0]) or {},
        records(files.json(_SOURCE_FILES[1]), "structures"),
    )
    return {
        _label_key(str(row.get("cpd") or row.get("compound_id") or "")): _frame(row)
        for row in catalog or []
    }


def recognition_sources(project: dict, compound_id: str) -> tuple[dict | None, tuple]:
    revision = source_revision(project)
    with _index_lock:
        binding = _source_index(str(project["run_root"]), revision).get(
            _label_key(compound_id)
        )
    return binding, revision


def source_context(binding: dict | None, root: str) -> str:
    value = encode({"root": root, "binding": binding})
    if len(value.encode()) > MAX_COMPLETION_BYTES:
        raise WebError(
            413,
            "recognition_source_limit",
            "Original source QC context exceeds its bounded collection limit.",
        )
    return value


def source_image_digest(
    project: dict, binding: dict | None, record: dict | None = None
) -> str | None:
    """One ordered source identity, not a cache of blobs, graphs or model results."""
    if binding is None:
        return None
    expected = [binding, *binding.get("additional_sources", [])]
    files = SafeFiles(Path(project["run_root"]))
    observations = (
        [record, *smiles_reprint_records(record)] if record is not None else []
    )
    if record is not None and not ordered_source_results(expected, observations):
        return None  # The shared completeness gate cannot qualify this observation.
    identities = []
    for index, source in enumerate(expected):
        path = files.relative(source.get("image_path") or "")
        if record is not None:
            observed = observations[index]
            original = (
                observed.get("ocsr_original_input")
                or observed.get("source_image_path")
                or source.get("image_path")
            )
            if files.relative(original or "") != path:
                raise WebError(
                    422,
                    "recognition_owner",
                    "Recognition points to another original source image.",
                )
            digest = observed.get("image_hash")
        else:
            from .recognition_storage import crop_digest

            digest = crop_digest(Path(project["run_root"]), str(path))
        identities.append(
            (
                _label_key(source.get("cpd") or source.get("compound_id")),
                source["structure_id"],
                digest,
            )
        )
    return hashlib.sha256(encode(identities).encode()).hexdigest()
