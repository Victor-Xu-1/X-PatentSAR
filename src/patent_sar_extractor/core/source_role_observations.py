"""Bounded rejected-role diagnostics in the existing artifacts, never role proof."""

import json
import math
import re
from itertools import pairwise

from .source_evidence_identity import proof_id

MAX_ROLE_ATTEMPTS = 4096
MAX_ROLE_CATALOG_BYTES = 64 * 1024 * 1024
_REASONS = {
    "cell_budget_exceeded",
    "native_measurement_conflict",
    "cell_render_limit",
    "unresolved_column_roles",
    "unqualified_role_observations",
}


def role_failure(reason, region, prefix, cells=None):
    """Keep the original attempted carrier, including incomplete/weak readings."""
    xs, ys = list(region["xs"]), list(region["ys"])
    return {
        "version": 1,
        "status": "unresolved",
        "reason": reason,
        "bbox": [xs[0], ys[0], xs[-1], ys[-1]],
        "xs": xs,
        "ys": ys,
        "prefix": prefix,
        "source_cells": cells,
    }


def scope_observations(observations, page_no, *, original_pdf_sha256=""):
    return [
        {
            **observation,
            "page_no": page_no,
            **(
                {"original_pdf_sha256": original_pdf_sha256}
                if original_pdf_sha256
                else {}
            ),
        }
        for observation in observations
    ]


def _bounded_tree(value, *, coordinate_tuples=False, max_depth=16, text_carriers=False):
    # A paired recovery wraps the existing reading in packet/views/selected;
    # failed attempts additionally wrap packet in attempts/list. Only this
    # explicit physical-cell owner gets the six carrier links, never an
    # arbitrary nested dictionary or another nested recovery. All node, array,
    # scalar and whole-catalog byte bounds remain shared and unchanged.
    owner = ("source_cells", "observations", "[]", "cells", "[]")
    pending, count = [(value, 0, max_depth, ())], 0
    while pending:
        item, depth, limit, path = pending.pop()
        count += 1
        if depth > limit or count > 200000:
            raise ValueError(
                "Original role diagnostic node inventory exceeds its budget"
            )
        if isinstance(item, dict):
            if len(item) > 128 or any(type(k) is not str or len(k) > 128 for k in item):
                raise ValueError("Malformed original role diagnostic object")
            for key, child in item.items():
                child_limit = (
                    max_depth + 6
                    if text_carriers
                    and path == owner
                    and key in {"auxiliary_text", "auxiliary_text_attempts"}
                    else limit
                )
                pending.append((child, depth + 1, child_limit, path + (key,)))
        elif isinstance(item, list) or coordinate_tuples and isinstance(item, tuple):
            if len(item) > 4096:
                raise ValueError("Original role diagnostic array exceeds its budget")
            pending.extend((child, depth + 1, limit, path + ("[]",)) for child in item)
        elif item is None or type(item) in {bool, int, str, float}:
            if (
                type(item) is str
                and len(item) > 10000
                or type(item) is float
                and not math.isfinite(item)
                or type(item) is int
                and item.bit_length() > 64
            ):
                raise ValueError("Original role diagnostic value exceeds its budget")
        else:
            raise TypeError("Original role diagnostic is not literal JSON")


def _validate(observation, *, original_pdf_sha256=None):
    if isinstance(observation, dict) and observation.get("version") == 2:
        from .binding_source_diagnostics import validate_binding_diagnostic
        from .caption_role_links import MAX_CONTINUATION_DEPTH

        validate_binding_diagnostic(
            observation, original_pdf_sha256=original_pdf_sha256
        )
        # A rejected proposal can contain the existing bounded64-page role chain.
        # Only this diagnostic variant has that depth; source acceptance does not.
        _bounded_tree(
            observation,
            coordinate_tuples=True,
            max_depth=16 + 3 * MAX_CONTINUATION_DEPTH,
        )
        return
    keys = {
        "version",
        "status",
        "reason",
        "page_no",
        "bbox",
        "xs",
        "ys",
        "prefix",
        "source_cells",
    }
    if not isinstance(observation, dict) or set(observation) not in (
        keys,
        keys | {"original_pdf_sha256"},
    ):
        raise ValueError("Malformed original role diagnostic")
    if (
        type(observation["version"]) is not int
        or observation["version"] != 1
        or observation["status"] != "unresolved"
        or observation["reason"] not in _REASONS
        or type(observation["page_no"]) is not int
        or not 1 <= observation["page_no"] <= 20000
        or not isinstance(observation["prefix"], str)
        or len(observation["prefix"]) > 10000
    ):
        raise ValueError("Malformed original role diagnostic status or source")
    for name in ("xs", "ys"):
        edges = observation[name]
        if (
            not isinstance(edges, list)
            or not 2 <= len(edges) <= 4096
            or any(
                type(x) not in {int, float}
                or not math.isfinite(x)
                or not 0 <= x <= 100000
                for x in edges
            )
            or any(b <= a for a, b in pairwise(edges))
        ):
            raise ValueError("Malformed original role diagnostic geometry")
    xs, ys = observation["xs"], observation["ys"]
    if observation["bbox"] != [xs[0], ys[0], xs[-1], ys[-1]]:
        raise ValueError("Original role diagnostic bounds differ")
    sha = observation.get("original_pdf_sha256")
    if sha is not None and (
        not isinstance(sha, str) or not re.fullmatch(r"[a-f0-9]{64}", sha)
    ):
        raise ValueError("Malformed original role diagnostic document")
    if original_pdf_sha256 is not None and sha != original_pdf_sha256:
        raise ValueError("Original role diagnostic belongs to a different document")
    cells = observation["source_cells"]
    if cells is not None and (
        not isinstance(cells, dict)
        or set(cells) - {"rendered_frames"}
        != {"xs", "ys", "native_hints", "observations"}
        or cells["xs"] != xs
        or cells["ys"] != ys
    ):
        raise ValueError("Original role diagnostic cell carrier differs")
    _bounded_tree(observation, text_carriers=True)


def _catalog(observations, *, expected_keys=None, original_pdf_sha256=None):
    if not isinstance(observations, list) or len(observations) > MAX_ROLE_ATTEMPTS:
        raise ValueError("Original role diagnostic inventory exceeds its budget")
    catalog, size = {}, 0
    for index, observation in enumerate(observations):
        _validate(observation, original_pdf_sha256=original_pdf_sha256)
        key = proof_id(observation)
        if expected_keys is not None and key != expected_keys[index]:
            raise ValueError("Original role diagnostic identity differs")
        if key in catalog:
            continue
        size += len(
            json.dumps(observation, ensure_ascii=False, allow_nan=False).encode("utf-8")
        )
        if size > MAX_ROLE_CATALOG_BYTES:
            raise ValueError("Original role diagnostic catalog exceeds its byte budget")
        catalog[key] = observation
    return catalog


class RoleObservationBuffer:
    """Bound live collection, not merely the final artifact after a long run."""

    def __init__(self):
        self._catalog = {}
        self._attempts = 0
        self._bytes = 0

    def __len__(self):
        return len(self._catalog)

    def __iter__(self):
        return iter(self._catalog.values())

    def extend(self, observations):
        for observation in observations:
            self._attempts += 1
            if self._attempts > MAX_ROLE_ATTEMPTS:
                raise ValueError(
                    "Original role diagnostic inventory exceeds its budget"
                )
            checked = _catalog([observation])
            key = next(iter(checked))
            if key in self._catalog:
                continue
            size = len(
                json.dumps(observation, ensure_ascii=False, allow_nan=False).encode(
                    "utf-8"
                )
            )
            if self._bytes + size > MAX_ROLE_CATALOG_BYTES:
                raise ValueError(
                    "Original role diagnostic catalog exceeds its byte budget"
                )
            self._bytes += size
            self._catalog[key] = observation


def serialize_role_observations(observations):
    """Deduplicate by the existing source digest; never truncate an inventory."""
    return _catalog(
        list(observations)
        if isinstance(observations, RoleObservationBuffer)
        else observations
    )


def validate_role_catalog(catalog, *, original_pdf_sha256=None):
    if not isinstance(catalog, dict) or len(catalog) > MAX_ROLE_ATTEMPTS:
        raise ValueError("Malformed original role diagnostic inventory")
    _catalog(
        list(catalog.values()),
        expected_keys=list(catalog),
        original_pdf_sha256=original_pdf_sha256,
    )
