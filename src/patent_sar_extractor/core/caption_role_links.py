"""Exact adjacent original-grid role links, independent of compound sequences."""

from .activity_context_geometry import validate_grid_axes
from .activity_grid_context import _prefix
from .caption_role_semantics import continuation_title, nonfinal_catalog_text
from .source_observations import source_claim_runs

MAX_CONTINUATION_DEPTH = 64


def valid_role_link(scope, link, prior_role, prior_key, local_key):
    if not isinstance(link, dict) or set(link) != {
        "previous",
        "previous_axes",
        "current_axes",
        "direction",
    }:
        return False
    previous = link["previous"]
    try:
        validate_grid_axes(link["previous_axes"], previous["table_bbox"])
        validate_grid_axes(link["current_axes"], scope["table_bbox"])
        old, new = link["previous_axes"], link["current_axes"]
        if old != previous.get("grid_axes") or new != scope.get("grid_axes"):
            return False
        if not (
            scope["page_no"] == previous["page_no"] + 1
            and new["ys"][0] < 150
            and prior_role in {"compound", "nonfinal"}
            and prior_key
            and link["direction"]
            in (
                {"above", "below"}
                if prior_role == "compound"
                else {"above", "below", None}
            )
            and len(old["xs"]) == len(new["xs"])
            and all(abs(a - b) <= 4 for a, b in zip(old["xs"], new["xs"], strict=True))
            and (not local_key or local_key == prior_key)
        ):
            return False
        region = {**new, "context_geometry": scope["context_geometry"]}
        for packet in scope["sources"]:
            if source_claim_runs(packet) is None:
                return False
            raw = _prefix(packet["tokens"], region)
            if nonfinal_catalog_text(raw):
                return False  # An explicit new role cannot borrow the old role.
        return bool(
            (
                local_key
                and all(
                    continuation_title(packet["text"])
                    for packet in scope["observations"]
                )
            )
            or not scope["observations"]
        )
    except (TypeError, ValueError, KeyError, AttributeError):
        return False


def role_link(previous, previous_axes, region, direction):
    return {
        "previous": previous,
        "previous_axes": previous_axes,
        "current_axes": {name: list(region[name]) for name in ("xs", "ys")},
        "direction": direction,
    }
