"""Strict source observation validation for all OCSR consumers, not a second QC."""

from __future__ import annotations

import math
import re
from typing import Any

from patent_sar_extractor.contracts import STEREO_EVIDENCE_VERSION

from .smiles_qc import qc_smiles
from .stereo_evidence import check_source_stereochemistry


def validate_stereo_record(record: dict[str, Any]) -> dict[str, Any]:
    evidence = record.get("stereochemistry")
    if (
        not isinstance(evidence, dict)
        or type(evidence.get("version")) is not int
        or evidence["version"] != STEREO_EVIDENCE_VERSION
    ):
        raise ValueError("Current source stereochemistry evidence is missing")
    digest = evidence.get("image_sha256")
    if (
        not isinstance(digest, str)
        or not re.fullmatch(r"[a-f0-9]{64}", digest)
        or digest != record.get("image_hash")
    ):
        raise ValueError("Source stereochemistry image identity is invalid")
    size, boxes = evidence.get("image_size"), evidence.get("unknown_bond_boxes")
    if (
        not isinstance(size, list)
        or len(size) != 2
        or any(type(n) is not int or n < 8 for n in size)
        or size[0] * size[1] > 16 * 1024 * 1024
    ):
        raise ValueError("Source stereochemistry image bounds are invalid")
    if not isinstance(boxes, list) or len(boxes) > 64:
        raise ValueError("Source unknown-bond observations exceed their limit")
    for box in boxes:
        if (
            not isinstance(box, list)
            or len(box) != 4
            or any(type(v) not in {int, float} or not math.isfinite(v) for v in box)
        ):
            raise ValueError("Source unknown-bond geometry is invalid")
        if not 0 <= box[0] < box[2] <= size[0] or not 0 <= box[1] < box[3] <= size[1]:
            raise ValueError("Source unknown-bond geometry is outside its image")
    raw = record.get("raw_smiles")
    if not isinstance(raw, str) or not 0 < len(raw) <= 10000:
        raise ValueError("Source stereochemistry has no bounded raw model observation")
    qc = qc_smiles(raw)
    from .stereo_rescue_pass import validate_rescue_proof

    validate_rescue_proof(record)
    expected = check_source_stereochemistry(
        qc,
        {
            "version": evidence["version"],
            "image_sha256": digest,
            "image_size": size,
            "unknown_bond_boxes": boxes,
        },
    )
    if any(evidence.get(key) != value for key, value in expected.items()):
        raise ValueError(
            "Source stereochemistry disagrees with the raw model observation"
        )
    if record.get("canonical_smiles") != qc.get("canonical_smiles"):
        raise ValueError(
            "Canonical molecule differs from the unmodified raw model observation"
        )
    return expected


def stereo_record_error(record: dict[str, Any]) -> str | None:
    try:
        evidence = validate_stereo_record(record)
    except ValueError as exc:
        return str(exc)
    if evidence["status"] in {"conflict", "ambiguous"}:
        return str(evidence["reason"])
    return None
