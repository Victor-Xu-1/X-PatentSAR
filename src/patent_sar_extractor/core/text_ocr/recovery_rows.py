"""One bounded row adapter for live capture and model-free deterministic replay."""

import copy
import re

from .cell_frames import MIN_AUXILIARY_SCORE
from .protocol import frame_digest, validate_reply


class UnqualifiedRecoveryRow(ValueError):
    """A valid source-owned reply was read but did not satisfy text quality."""


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
        raise UnqualifiedRecoveryRow("Auxiliary recovery row remains unqualified")
    return result


def qualified(result):
    return bool(result["text"].strip() and result["confidence"] >= MIN_AUXILIARY_SCORE)


def checked_group(group, fingerprint=None, *, version=3):
    from .row_preparation import preparation_shapes

    if not isinstance(group, dict) or "observations" not in group:
        raise ValueError("Missing auxiliary row observations")
    shapes = preparation_shapes(
        {k: v for k, v in group.items() if k != "observations"}, version=version
    )
    observations = group["observations"]
    if not isinstance(observations, list) or not 1 <= len(observations) <= len(shapes):
        raise ValueError("Unbounded auxiliary row observations")
    first = checked_row(observations[0], fingerprint, require_quality=False)
    if first["pixel_sha256"] != group["source_pixel_sha256"]:
        raise ValueError("Auxiliary row lost its original pixel ownership")
    results = [
        checked_row(observed, first["model_fingerprint"], require_quality=False)
        for observed in observations
    ]
    if any(qualified(result) for result in results[:-1]) or (
        not qualified(results[-1]) and len(results) != len(shapes)
    ):
        raise ValueError("Auxiliary padding retry differs from its bounded policy")
    selected = checked_row(observations[-1], first["model_fingerprint"])
    if len({result["pixel_sha256"] for result in results}) != len(results):
        raise ValueError("Auxiliary padding retry repeated unchanged pixels")
    return selected


class RecoveryRowEngine:
    """Detection uses existing original rows; only bounded row recognition calls out."""

    def __init__(
        self,
        *,
        auxiliary=None,
        requests=None,
        budget=None,
        fingerprint=None,
        version=3,
        retained_rows=(),
    ):
        self.auxiliary = auxiliary
        self.requests = [] if requests is None else requests
        self.budget = [] if budget is None else budget
        self.fingerprint = fingerprint
        self.position = 0
        self.version = version
        self.retained_rows = retained_rows

    def __call__(self, image, *, use_det, use_cls):
        if use_cls:
            raise ValueError("Auxiliary source rows cannot change orientation")
        if use_det:
            return [], None
        from .source_inventory import _MAX_ROWS

        frame_digest(image)  # Preserve the unchanged single-row pixel/size limit.
        retained = (
            self.retained_rows[self.position]
            if self.position < len(self.retained_rows)
            else None
        )
        if self.version >= 5 and retained is not None:
            from .recovery_retained_rows import (
                checked_retained_request,
                retained_request,
            )

            if self.auxiliary is not None:
                self.requests.append(retained_request(retained, self.position, image))
            if self.position >= len(self.requests):
                raise ValueError("Missing retained primary row request")
            result = checked_retained_request(
                self.requests[self.position], retained, self.position, pixels=image
            )
            self.position += 1
            return [[result["text"], result["confidence"]]], None
        if self.version == 2 and self.auxiliary is None:
            if self.position >= len(self.requests):
                raise ValueError("Original recovery requires an unrecorded source row")
            observed = self.requests[self.position]
            result = checked_row(observed, self.fingerprint, pixels=image)
        else:
            from .row_preparation import preparation_views

            frame, variants = preparation_views(image, version=self.version)
            if self.auxiliary is None:
                if self.position >= len(self.requests):
                    raise ValueError(
                        "Original recovery requires an unrecorded source row"
                    )
                group = self.requests[self.position]
                if {k: v for k, v in group.items() if k != "observations"} != frame:
                    raise ValueError("Original row preparation changed")
                result = checked_group(group, self.fingerprint, version=self.version)
                for pixels, observed in zip(variants, group["observations"]):
                    checked_row(
                        observed, self.fingerprint, pixels=pixels, require_quality=False
                    )
            else:
                group = {**frame, "observations": []}
                self.requests.append(group)
                for pixels in variants:
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
                result = checked_group(group, self.fingerprint, version=self.version)
        self.fingerprint = result["model_fingerprint"]
        self.position += 1
        return [[result["text"], result["confidence"]]], None

    def complete(self):
        return self.position == len(self.requests)
