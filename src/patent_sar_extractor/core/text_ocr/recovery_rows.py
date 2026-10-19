"""One bounded row adapter for live capture and model-free deterministic replay."""

import copy
import re

from .cell_frames import MIN_AUXILIARY_SCORE
from .protocol import frame_digest, validate_reply


def checked_row(observed, fingerprint=None, *, pixels=None):
    if not isinstance(observed, dict) or type(observed.get("cache_hit")) is not bool:
        raise ValueError("Malformed auxiliary recovery row")
    response = {key: value for key, value in observed.items() if key != "cache_hit"}
    for key, size in (
        ("id", 32),
        ("image_sha256", 64),
        ("pixel_sha256", 64),
        ("model_fingerprint", 64),
    ):
        if not isinstance(response.get(key), str) or not re.fullmatch(
            rf"[a-f0-9]{{{size}}}", response[key]
        ):
            raise ValueError("Unproved auxiliary recovery row identity")
    request = {
        key: response[key]
        for key in ("id", "image_sha256", "pixel_sha256", "model_fingerprint")
    }
    if fingerprint is not None:
        request["model_fingerprint"] = fingerprint
    if pixels is not None:
        request["pixel_sha256"] = frame_digest(pixels)
    result = validate_reply(response, request)
    if not result["text"].strip() or result["confidence"] < MIN_AUXILIARY_SCORE:
        raise ValueError("Auxiliary recovery row remains unqualified")
    return result


class RecoveryRowEngine:
    """Detection uses existing original rows; only bounded row recognition calls out."""

    def __init__(self, *, auxiliary=None, requests=None, budget=None, fingerprint=None):
        self.auxiliary = auxiliary
        self.requests = [] if requests is None else requests
        self.budget = [] if budget is None else budget
        self.fingerprint = fingerprint
        self.position = 0

    def __call__(self, image, *, use_det, use_cls):
        if use_cls:
            raise ValueError("Auxiliary source rows cannot change orientation")
        if use_det:
            return [], None
        from .source_inventory import _MAX_ROWS

        frame_digest(image)  # Preserve the unchanged single-row pixel/size limit.
        if self.auxiliary is None:
            if self.position >= len(self.requests):
                raise ValueError("Original recovery requires an unrecorded source row")
            observed = self.requests[self.position]
        else:
            if len(self.budget) >= _MAX_ROWS:
                raise ValueError("Auxiliary original row inventory exceeds its budget")
            observed = self.auxiliary.observe(image)
            self.requests.append(copy.deepcopy(observed))
            self.budget.append(None)
        result = checked_row(observed, self.fingerprint, pixels=image)
        self.fingerprint = result["model_fingerprint"]
        self.position += 1
        return [[result["text"], result["confidence"]]], None

    def complete(self):
        return self.position == len(self.requests)
