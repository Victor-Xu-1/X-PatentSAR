"""Bounded original-input currentness for core chemistry, without reparsing on polls."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from patent_sar_extractor.contracts import MAX_RECOGNITION_SOURCES
from patent_sar_extractor.core.pipeline_rules import _label_key
from patent_sar_extractor.smiles_artifact import (
    smiles_reprint_records,
    smiles_source_records,
)

from .errors import WebError
from .files import SafeFiles


@dataclass(frozen=True)
class CoreSources:
    primary: dict
    reprints: dict


@lru_cache(maxsize=8)
def _inputs(root: str, signature: tuple) -> CoreSources:
    files = SafeFiles(Path(root))
    payload = files.json("smiles/smiles_results.json")
    records = [*payload.get("records", []), *smiles_source_records(payload)]
    repeated = smiles_reprint_records(payload)
    if len(records) + len(repeated) > MAX_RECOGNITION_SOURCES:
        raise ValueError("Core source observations exceed their bound")
    result = {}
    reprints = {}
    for index, record in enumerate([*records, *repeated]):
        if not isinstance(record, dict):
            raise TypeError("Core source observation is invalid")
        key = _label_key(str(record.get("cpd_id") or "")), record.get("structure_id")
        if key in result:
            raise ValueError("Core source owner is duplicated")
        result[key] = (
            record.get("ocsr_original_input") or record.get("source_image_path"),
            record.get("image_hash"),
        )
        if index >= len(records):
            reprints.setdefault(key[0], []).append(result[key])
    return CoreSources(result, reprints)


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
        inputs = _inputs(str(root), signature)
        owner = _label_key(compound.id)
        original, digest = inputs.primary.get(
            (owner, compound.structure_id), (None, None)
        )
        if digest != evidence.image_sha256:
            return False
        path = SafeFiles(root).relative(original or row["image_path"])
        if crop_digest(root, path) != digest:
            return False
        reprints = inputs.reprints.get(owner, [])
        if len(reprints) != len(getattr(compound, "additional_sources", [])):
            return False
        return all(
            source and crop_digest(root, SafeFiles(root).relative(source)) == expected
            for source, expected in reprints
        )
    except (WebError, OSError, ValueError, TypeError, KeyError):
        return False
