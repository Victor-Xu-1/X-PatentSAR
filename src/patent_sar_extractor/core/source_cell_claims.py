"""Semantic use of original cell observations, shared by producers and replay."""

import re

from .activity_header_metrics import explicit_unit, literal_header_units
from .activity_values import (
    is_explicit_missing_activity_value,
    normalize_activity_value_token,
)
from .cell_caption_identity import caption_fragment_conflict
from .compound_caption import prefixed_label
from .printed_identifiers import (
    LABEL_KIND,
    identifier_fragments_conflict,
    identifier_key,
)
from .source_observations import source_claim_runs, source_observation_status
from .source_section_roles import nonfinal_original_label


def cell_source_status(observation):
    if "source_observation" not in observation:
        return "legacy"
    packet = observation["source_observation"]
    if not isinstance(packet, dict):
        return "invalid"
    expected = "native" if observation.get("method") == "native_cell" else "raster"
    if packet.get("origin") != expected:
        return "invalid"
    return source_observation_status(
        packet, observation.get("bbox", packet.get("bbox")), observation.get("text")
    )


def _identity_conflict(raw, candidate, kind, *, fragment=False):
    candidate = identifier_key(candidate, wrapped=True, terminal_period=True)
    if not candidate:
        return bool(raw.strip())
    if nonfinal_original_label(raw) or re.fullmatch(
        r"Intermediate|中间体", raw.strip(), re.IGNORECASE
    ):
        return True
    observed = (
        prefixed_label(raw)
        if kind == "label"
        else identifier_key(raw, wrapped=True, terminal_period=True)
    )
    if observed:
        return observed != candidate
    if kind == "label" and fragment:
        return caption_fragment_conflict(raw, candidate)
    # A bare label-kind word nominates a caption, but claims no printed number.
    if kind == "label" and re.fullmatch(
        rf"(?:{LABEL_KIND})s?", raw.strip(), re.IGNORECASE
    ):
        return False
    return identifier_fragments_conflict(raw, candidate, caption=kind == "label")


def _value_conflict(raw, candidate, *, fragment=False):
    if is_explicit_missing_activity_value(raw) and is_explicit_missing_activity_value(
        candidate
    ):
        return False
    old, new = (
        normalize_activity_value_token(raw),
        normalize_activity_value_token(candidate),
    )
    if not fragment:
        return bool(old and re.sub(r"\s+", "", old) != re.sub(r"\s+", "", new))
    if not literal_header_units(raw).issubset(literal_header_units(candidate)):
        return True
    if re.search(r"[<>≤≥%±*]", raw):
        return any(symbol not in candidate for symbol in re.findall(r"[<>≤≥%±*]", raw))
    if explicit_unit(raw):
        return False
    return bool(old and re.sub(r"\s+", "", old) not in re.sub(r"\s+", "", new))


def cell_source_conflict(observation, candidate, kind):
    status = cell_source_status(observation)
    if status == "invalid":
        return True
    raw = str(observation.get("text") or "")
    if status == "empty":
        return False
    check = _identity_conflict if kind in {"id", "label"} else _value_conflict
    if status in {"legacy", "qualified"}:
        return (
            check(raw, candidate, kind)
            if kind in {"id", "label"}
            else check(raw, candidate)
        )
    runs = source_claim_runs(observation["source_observation"])
    if runs is None:
        return True
    return any(
        check(" ".join(run), candidate, kind, fragment=True)
        if kind in {"id", "label"}
        else check(" ".join(run), candidate, fragment=True)
        for run in runs
    )
