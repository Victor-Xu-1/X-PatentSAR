"""One bounded row adapter for live capture and model-free deterministic replay."""

import copy
import re

from .cell_frames import MIN_AUXILIARY_SCORE
from .protocol import frame_digest, validate_reply


def checked_row(observed, fingerprint=None, *, pixels=None, require_quality=True):
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
    if require_quality and not qualified(result):
        raise ValueError("Auxiliary recovery row remains unqualified")
    return result


def qualified(result):
    return bool(result["text"].strip() and result["confidence"] >= MIN_AUXILIARY_SCORE)


def checked_group(group, fingerprint=None):
    from .row_preparation import checked_frame

    if not isinstance(group, dict) or "observations" not in group:
        raise ValueError("Missing auxiliary row observations")
    compact = checked_frame({k: v for k, v in group.items() if k != "observations"})
    observations = group["observations"]
    if not isinstance(observations, list) or not 1 <= len(observations) <= 2:
        raise ValueError("Unbounded auxiliary row observations")
    first = checked_row(observations[0], fingerprint, require_quality=False)
    if first["pixel_sha256"] != group["source_pixel_sha256"]:
        raise ValueError("Auxiliary row lost its original pixel ownership")
    extra = not qualified(first) and compact is not None
    if len(observations) != 1 + int(extra):
        raise ValueError("Auxiliary padding retry differs from its bounded policy")
    selected = checked_row(observations[-1], first["model_fingerprint"])
    if extra and selected["pixel_sha256"] == first["pixel_sha256"]:
        raise ValueError("Auxiliary padding retry repeated unchanged pixels")
    return selected


class RecoveryRowEngine:
    """Detection uses existing original rows; only bounded row recognition calls out."""

    def __init__(
        self, *, auxiliary=None, requests=None, budget=None, fingerprint=None, version=3
    ):
        self.auxiliary = auxiliary
        self.requests = [] if requests is None else requests
        self.budget = [] if budget is None else budget
        self.fingerprint = fingerprint
        self.position = 0
        self.version = version

    def __call__(self, image, *, use_det, use_cls):
        if use_cls:
            raise ValueError("Auxiliary source rows cannot change orientation")
        if use_det:
            return [], None
        from .source_inventory import _MAX_ROWS

        frame_digest(image)  # Preserve the unchanged single-row pixel/size limit.
        if self.version == 2 and self.auxiliary is None:
            if self.position >= len(self.requests):
                raise ValueError("Original recovery requires an unrecorded source row")
            observed = self.requests[self.position]
            result = checked_row(observed, self.fingerprint, pixels=image)
        else:
            from .row_preparation import row_frame

            frame, alternate = row_frame(image)
            if self.auxiliary is None:
                if self.position >= len(self.requests):
                    raise ValueError(
                        "Original recovery requires an unrecorded source row"
                    )
                group = self.requests[self.position]
                if {k: v for k, v in group.items() if k != "observations"} != frame:
                    raise ValueError("Original row preparation changed")
                result = checked_group(group, self.fingerprint)
                for pixels, observed in zip((image, alternate), group["observations"]):
                    checked_row(
                        observed, self.fingerprint, pixels=pixels, require_quality=False
                    )
            else:
                group = {**frame, "observations": []}
                self.requests.append(group)
                for pixels in (image, alternate):
                    if pixels is None:
                        break
                    if len(self.budget) >= _MAX_ROWS:
                        raise ValueError(
                            "Auxiliary original row inventory exceeds its budget"
                        )
                    self.budget.append(None)
                    observed = self.auxiliary.observe(pixels)
                    group["observations"].append(copy.deepcopy(observed))
                    result = checked_row(
                        observed, self.fingerprint, pixels=pixels, require_quality=False
                    )
                    self.fingerprint = result["model_fingerprint"]
                    if qualified(result):
                        break
                result = checked_group(group, self.fingerprint)
        self.fingerprint = result["model_fingerprint"]
        self.position += 1
        return [[result["text"], result["confidence"]]], None

    def complete(self):
        return self.position == len(self.requests)
