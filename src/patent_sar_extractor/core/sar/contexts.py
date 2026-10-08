"""Validate observation packets and all recorded conditions before comparison."""

from __future__ import annotations

from typing import Any

from .errors import SARInputError
from .limits import (
    MAX_CONTEXT_CHARS,
    MAX_CONTEXT_FIELDS,
    MAX_OBSERVATIONS,
    MAX_VALUE_CHARS,
)

# DTO has no context-complete flag. Require these common conditions; callers
# must explicitly record not-applicable fields or request user confirmation.
REQUIRED_CONTEXT = frozenset({"target", "assay", "cell_line", "duration"})
UNKNOWN_CONTEXT = {"", "unknown", "not recorded", "not specified"}


def select_observations(raw: object, metric_id: str) -> list[dict[str, Any]]:
    if not isinstance(raw, (list, tuple)):
        raise SARInputError("invalid_observations")
    if len(raw) > MAX_OBSERVATIONS:
        raise SARInputError("observation_limit_exceeded")
    selected = []
    for observation in raw:
        if not isinstance(observation, dict) or not isinstance(
            observation.get("metric_id"), str
        ):
            raise SARInputError("invalid_observation")
        if observation["metric_id"] != metric_id:
            continue
        value, unit, context = (
            observation.get("value"),
            observation.get("unit"),
            observation.get("context", {}),
        )
        if not isinstance(value, str) or len(value) > MAX_VALUE_CHARS:
            raise SARInputError("invalid_observation_value")
        if unit is not None and (
            not isinstance(unit, str) or len(unit) > MAX_CONTEXT_CHARS
        ):
            raise SARInputError("invalid_observation_unit")
        if not isinstance(context, dict) or len(context) > MAX_CONTEXT_FIELDS:
            raise SARInputError("invalid_observation_context")
        if any(
            not isinstance(key, str)
            or not key
            or len(key) > MAX_CONTEXT_CHARS
            or (
                value is not None
                and (not isinstance(value, str) or len(value) > MAX_CONTEXT_CHARS)
            )
            for key, value in context.items()
        ):
            raise SARInputError("invalid_observation_context")
        selected.append(observation)
    return selected


def _known(value: str | None) -> str | None:
    if value is None or value.strip().casefold() in UNKNOWN_CONTEXT:
        return None
    return value.strip()


def compare_context(
    observations: list[dict[str, Any]], *, ordinal: bool, confirmed: bool
) -> tuple[str, list[str], bool]:
    """Return evidence basis, safe reasons, and a known-conflict flag.

    Exact units only: no implicit conversion, synonym or target/assay inference.
    Explicit confirmation covers unknown conditions, never conflicting facts.
    """
    reasons = []
    contexts = [observation.get("context", {}) for observation in observations]
    fields = REQUIRED_CONTEXT | {key for context in contexts for key in context}
    missing = False
    for key in sorted(fields):
        recorded = [_known(context.get(key)) for context in contexts]
        if len({value for value in recorded if value is not None}) > 1:
            reasons.append("recorded_context_conflict")
        if any(value is None for value in recorded):
            missing = True
    units = [_known(observation.get("unit")) for observation in observations]
    known_units = {unit for unit in units if unit is not None}
    if len(known_units) > 1:
        reasons.append("unit_conflict")
    # If a caller redundantly records unit inside context it must agree too.
    context_units = {_known(context.get("unit")) for context in contexts} - {None}
    if len(known_units | context_units) > 1:
        reasons.append("unit_conflict")
    if reasons:
        return "insufficient", sorted(set(reasons)), True
    if not ordinal and any(unit is None for unit in units):
        missing = True
        reasons.append("unit_missing")
    if missing:
        reasons.append("context_incomplete")
        if confirmed:
            return "user_confirmed", reasons + ["context_user_confirmed"], False
        return "insufficient", reasons, False
    return "recorded_context", [], False
