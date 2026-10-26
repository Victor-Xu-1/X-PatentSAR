"""Pure replay of an original catalogue title, never a trusted role flag."""

from itertools import pairwise

from .activity_context_geometry import (
    context_floor,
    valid_box,
    validate_context_geometry,
    validate_grid_axes,
)
from .caption_role_links import MAX_CONTINUATION_DEPTH, valid_role_link
from .caption_role_titles import project_caption_titles
from .source_observations import source_observation_status
from .source_table_roles import observed_role, title_key
from .title_context_grids import caption_title_context, validate_parallel_title_grids
from .title_context_source import valid_title_context

__all__ = [
    "caption_role_status",
    "observed_role",
    "title_key",
    "validate_caption_exclusions",
]


def caption_role_status(scope, page_no, label_cell, *, _depth=0):
    """Return the rederived role or None when its original frame is invalid."""
    if (
        _depth > MAX_CONTINUATION_DEPTH
        or type(page_no) is not int
        or not isinstance(scope, dict)
        or set(scope) - {"continuation", "parallel_grids"}
        != {
            "version",
            "page_no",
            "table_bbox",
            "grid_axes",
            "context_geometry",
            "window",
            "observations",
            "role",
            "table_key",
            "sources",
        }
    ):
        return None
    if (
        type(scope["version"]) is not int
        or scope["version"] != 1
        or type(scope["page_no"]) is not int
        or scope["page_no"] != page_no
        or not 1 <= page_no <= 20000
        or not valid_box(label_cell)
        or not valid_box(scope["table_bbox"])
        or not valid_box(scope["window"])
        or not isinstance(scope["observations"], list)
        or not 0 <= len(scope["observations"]) <= 2
    ):
        return None
    table, window = scope["table_bbox"], scope["window"]
    try:
        validate_context_geometry(scope["context_geometry"], table)
        validate_grid_axes(scope["grid_axes"], table)
        validate_parallel_title_grids(caption_title_context(scope))
        if label_cell != table and (
            (label_cell[0], label_cell[2])
            not in tuple(pairwise(scope["grid_axes"]["xs"]))
            or (label_cell[1], label_cell[3])
            not in tuple(pairwise(scope["grid_axes"]["ys"]))
        ):
            return None
        if window[1] != context_floor(scope["context_geometry"]):
            return None
    except (ValueError, TypeError, KeyError):
        return None
    if not (
        window[0] == 0
        and window[3] == table[1]
        and table[2] <= window[2]
        and table[0] <= label_cell[0] < label_cell[2] <= table[2]
        and table[1] <= label_cell[1] < label_cell[3] <= table[3]
    ):
        return None
    for packet in scope["observations"]:
        if (
            not isinstance(packet, dict)
            or not valid_box(packet.get("bbox"))
            or not isinstance(packet.get("tokens"), list)
            or not 1 <= len(packet["tokens"]) <= 64
            or source_observation_status(packet, packet["bbox"], packet.get("text"))
            == "invalid"
        ):
            return None
        box = packet["bbox"]
        if not (
            window[0] <= box[0] < box[2] <= window[2]
            and window[1] <= box[1] < box[3] <= window[3]
        ):
            return None
    role, key = observed_role(
        scope["observations"],
        contexts=scope["sources"],
        context=caption_title_context(scope),
    )
    try:
        if (
            not isinstance(scope["sources"], list)
            or not 1 <= len(scope["sources"]) <= 2
            or any(
                not valid_title_context(packet, page_no=page_no, width=window[2])
                for packet in scope["sources"]
            )
        ):
            return None
        if any(packet.get("bbox") != window for packet in scope["sources"]):
            return None
        if scope["observations"] != project_caption_titles(
            scope["sources"], scope["context_geometry"]
        ):
            return None
    except (ValueError, TypeError, KeyError, AttributeError):
        return None
    if "continuation" in scope:
        if role != "unknown":
            return None
        link = scope["continuation"]
        if not isinstance(link, dict) or not isinstance(link.get("previous"), dict):
            return None
        previous = link["previous"]
        prior = caption_role_status(
            previous,
            previous.get("page_no"),
            previous.get("table_bbox"),
            _depth=_depth + 1,
        )
        if not valid_role_link(scope, link, prior, previous.get("table_key"), key):
            return None
        role, key = prior, previous["table_key"]
    return role if (scope["role"], scope["table_key"]) == (role, key) else None


def validate_caption_exclusions(sections, entries):
    """Explicit nonfinal regions are retained and cannot supply final structures."""
    excluded = set()
    for section in sections:
        if section.get("role") != "nonfinal_caption_catalog":
            continue
        if (
            set(section)
            != {"role", "status", "page_no", "bbox", "caption_role", "structure_ids"}
            or section["status"] != "observed_nonfinal_caption_catalog"
            or not isinstance(section["caption_role"], dict)
            or not isinstance(section["structure_ids"], list)
            or len(section["structure_ids"]) > 100000
            or any(
                not isinstance(identity, str) or not 0 < len(identity) <= 256
                for identity in section["structure_ids"]
            )
            or len(set(section["structure_ids"])) != len(section["structure_ids"])
            or section["bbox"] != section["caption_role"].get("table_bbox")
            or caption_role_status(
                section["caption_role"], section["page_no"], section["bbox"]
            )
            != "nonfinal"
        ):
            raise ValueError("Unproved original nonfinal caption catalogue")
        excluded.update(section["structure_ids"])
    if any(entry.get("structure_id") in excluded for entry in entries):
        raise ValueError(
            "Original nonfinal catalogue was promoted into final structures"
        )
