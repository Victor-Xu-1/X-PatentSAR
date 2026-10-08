"""Exact recorded-context identities shared by study admission and statistics."""

from __future__ import annotations

import hashlib
import json
from collections import Counter

from .errors import SARInputError


def context_identity(observation: dict) -> str:
    """No case folding, missing-condition filling, unit conversion or translation."""
    payload = [
        observation["metric_id"],
        observation.get("unit"),
        sorted(observation.get("context", {}).items()),
    ]
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def context_catalog(molecules: list[dict], metrics: list[dict]) -> list[dict]:
    known = {metric["id"]: metric for metric in metrics}
    groups: dict[str, dict] = {}
    values: dict[str, Counter] = {}
    ids: dict[str, set[str]] = {}
    count = 0
    for molecule in molecules:
        for observation in molecule["observations"]:
            count += 1
            if count > 100000:
                raise SARInputError("study_observation_limit")
            metric = known.get(observation["metric_id"])
            if metric is None:
                raise SARInputError("study_metric_identity")
            key = context_identity(observation)
            if key not in groups:
                if len(groups) >= 1000:
                    raise SARInputError("study_context_limit")
                groups[key] = {
                    "id": key,
                    "metric_id": metric["id"],
                    "name": metric["name"],
                    "unit": observation.get("unit"),
                    "context": observation.get("context", {}),
                }
                values[key], ids[key] = Counter(), set()
            values[key][observation["value"]] += 1
            ids[key].add(molecule["id"])
    return [
        {
            **group,
            "molecule_count": len(ids[key]),
            "observation_count": values[key].total(),
            "distinct_value_count": len(values[key]),
            "value_samples": sorted(values[key])[:32],
        }
        for key, group in groups.items()
    ]


def context_observations(molecule: dict, identifier: str) -> list[dict]:
    return [
        item
        for item in molecule["observations"]
        if context_identity(item) == identifier
    ]
