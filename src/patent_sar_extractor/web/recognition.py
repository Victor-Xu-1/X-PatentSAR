"""Separate recorded recognition quality from binding and manual decisions."""

from __future__ import annotations

import math
import re
from typing import Any

from .errors import WebError


def recognition_status(record: dict[str, Any], *, current: bool) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": "not_run",
        "quality_flag": None,
        "model_fingerprint": None,
        "token_confidence": None,
    }
    if not record:
        return result
    if not current:
        result["status"] = "unavailable"
        return result
    flag = record.get("OCSR_quality_flag")
    if flag is not None and (not isinstance(flag, str) or len(flag) > 100):
        raise WebError(
            422, "invalid_recognition", "Recognition quality metadata is invalid."
        )
    result["quality_flag"] = flag
    result["status"] = (
        "unavailable"
        if flag is None
        or record.get("OCSR_status")
        in {"unavailable", "engine_unavailable", "image_missing"}
        else "valid"
        if record.get("rdkit_valid") is True and flag == "ok"
        else "invalid"
    )
    fingerprint = record.get("model_fingerprint")
    if fingerprint is not None and (
        not isinstance(fingerprint, str)
        or not re.fullmatch(r"[a-f0-9]{64}", fingerprint)
    ):
        raise WebError(
            422, "invalid_recognition", "Recognition model identity is invalid."
        )
    result["model_fingerprint"] = fingerprint
    confidence = record.get("token_confidence")
    if confidence is not None:
        if (
            not isinstance(confidence, dict)
            or set(confidence) != {"minimum", "mean"}
            or any(
                type(value) not in {float, int}
                or not math.isfinite(value)
                or not 0 <= value <= 1
                for value in confidence.values()
            )
            or confidence["minimum"] > confidence["mean"]
        ):
            raise WebError(
                422, "invalid_recognition", "Uncalibrated token confidence is invalid."
            )
        result["token_confidence"] = confidence
    return result
