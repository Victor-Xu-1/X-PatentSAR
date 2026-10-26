"""Exact adjacent original-grid role links, independent of compound sequences."""

from .activity_context_geometry import validate_grid_axes
from .activity_grid_context import _prefix
from .caption_boundary_context import valid_caption_tail
from .caption_role_semantics import continuation_title, nonfinal_catalog_text
from .source_observations import source_claim_runs
from .source_table_roles import title_texts
from .structure_table_headers import aligned_column_edges
from .title_context_grids import caption_title_context

MAX_CONTINUATION_DEPTH = 64


def valid_role_link(scope, link, prior_role, prior_key, local_key):
    if not isinstance(link, dict) or set(link) != {
        "previous",
        "previous_axes",
        "current_axes",
        "direction",
        "previous_tail",
    }:
        return False
    previous = link["previous"]
    try:
        validate_grid_axes(link["previous_axes"], previous["table_bbox"])
        validate_grid_axes(link["current_axes"], scope["table_bbox"])
        old, new = link["previous_axes"], link["current_axes"]
        if old != previous.get("grid_axes") or new != scope.get("grid_axes"):
            return False
        if not valid_caption_tail(link["previous_tail"], previous):
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
            and aligned_column_edges(old["xs"], new["xs"])
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
        titles = title_texts(
            scope["observations"],
            contexts=scope["sources"],
            context=caption_title_context(scope),
        )
        return bool(
            (local_key and titles and all(continuation_title(text) for text in titles))
            or not titles
        )
    except (TypeError, ValueError, KeyError, AttributeError):
        return False


def role_link(previous, previous_axes, region, direction, previous_tail):
    return {
        "previous": previous,
        "previous_axes": previous_axes,
        "current_axes": {name: list(region[name]) for name in ("xs", "ys")},
        "direction": direction,
        "previous_tail": previous_tail,
    }
