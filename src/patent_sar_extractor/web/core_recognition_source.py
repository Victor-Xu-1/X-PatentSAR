"""Bounded original-input currentness for core chemistry, without reparsing on polls."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from .errors import WebError
from .files import SafeFiles


@lru_cache(maxsize=8)
def _inputs(root: str, signature: tuple) -> dict:
    files = SafeFiles(Path(root))
    payload = files.json("smiles/smiles_results.json")
    records = [*payload.get("records", []), *payload.get("source_records", [])]
    if len(records) > 25000:
        raise ValueError("Core source observations exceed their bound")
    result = {}
    for record in records:
        if not isinstance(record, dict):
            raise TypeError("Core source observation is invalid")
        key = record.get("cpd_id"), record.get("structure_id")
        if key in result:
            raise ValueError("Core source owner is duplicated")
        result[key] = (
            record.get("ocsr_original_input") or record.get("source_image_path"),
            record.get("image_hash"),
        )
    return result


def core_source_current(project: dict, row: dict, compound) -> bool:
    """New masked-input paths are explicit; legacy display input is never guessed."""
    from .recognition_storage import crop_digest

    evidence = compound.recognition.stereochemistry
    if evidence is None or not compound.smiles:
        return True  # This cannot qualify absent/rejected chemistry.
    try:
        root = Path(project["run_root"])
        with SafeFiles(root).open(
            "smiles/smiles_results.json", max_bytes=64 * 1024 * 1024
        ) as stream:
            info = os.fstat(stream.fileno())
        signature = (
            info.st_dev,
            info.st_ino,
            info.st_size,
            info.st_mtime_ns,
            info.st_ctime_ns,
        )
        original, digest = _inputs(str(root), signature).get(
            (compound.id, compound.structure_id), (None, None)
        )
        if digest != evidence.image_sha256:
            return False
        path = SafeFiles(root).relative(original or row["image_path"])
        return crop_digest(root, path) == digest
    except (WebError, OSError, ValueError, TypeError, KeyError):
        return False
