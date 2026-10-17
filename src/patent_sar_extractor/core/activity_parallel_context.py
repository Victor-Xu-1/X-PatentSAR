"""Replay a unique shared original caption; no OCR, value or assay inference."""

from .activity_caption_windows import shared_caption_allowed
from .activity_context_geometry import grid_box, valid_box, validate_context_geometry
from .activity_grid_context import _prefix
from .activity_header_sources import context_source_parts, source_context_region
from .activity_headers import context_from_text
from .source_geometry import SourceTokens, native_region
from .source_observations import (
    source_cell_observation,
    source_claim_runs,
    source_observation_status,
)
from .source_window_chunks import validate_source_overlap


def observe_parallel_context(page, region, tokens):
    geometry = region.get("context_geometry", {})
    span = geometry.get("parallel_span")
    if (
        not isinstance(tokens, SourceTokens)
        or not span
        or span == [region["xs"][0], region["xs"][-1]]
    ):
        return None
    bounds = [0, max(0, region["ys"][0] - 310), page.rect.width, region["ys"][0]]
    if not valid_box(bounds):
        return None
    return {
        "version": 1,
        "page_size": [page.rect.width, page.rect.height],
        "prefix": source_cell_observation(
            tokens, bounds, native=native_region(tokens, bounds, False)
        ),
        "native_prefix": source_cell_observation(tokens, bounds, native=True),
    }


def validate_parallel_context(region, prefix=None):
    scope = region.get("parallel_context")
    if scope is None:
        return None
    if (
        not isinstance(scope, dict)
        or set(scope) != {"version", "page_size", "prefix", "native_prefix"}
        or type(scope["version"]) is not int
        or scope["version"] != 1
        or not isinstance(scope["page_size"], list)
        or len(scope["page_size"]) != 2
        or not valid_box([0, 0, *scope["page_size"]])
    ):
        raise ValueError("Malformed original shared-panel context")
    size, geometry, box = (
        scope["page_size"],
        region.get("context_geometry"),
        grid_box(region),
    )
    validate_context_geometry(geometry, box)
    if box[2] > size[0] or box[3] > size[1]:
        raise ValueError("Original shared-panel context leaves its page")
    bounds = [0, max(0, box[1] - 310), size[0], box[1]]
    for name in ("prefix", "native_prefix"):
        packet = scope[name]
        if (
            not isinstance(packet, dict)
            or source_observation_status(packet, bounds, packet.get("text"))
            == "invalid"
        ):
            raise ValueError("Invalid original shared-panel source observation")
    primary, native = scope["prefix"], scope["native_prefix"]
    if (
        native["origin"] != "native"
        or primary["origin"] == "native"
        and primary != native
    ):
        raise ValueError("Conflicting original shared-panel source origins")
    shared = shared_caption_allowed((primary["tokens"], native["tokens"]), region)
    if (
        prefix is not None
        and _prefix(primary["tokens"], {**region, "allow_shared_caption": shared})
        != prefix
    ):
        raise ValueError("Original shared-panel boundary differs from retained facts")
    return scope, bounds, shared


def _qualified(region, prefix):
    checked = validate_parallel_context(region, prefix)
    if checked is None or not checked[2]:
        return None
    scope, bounds, _ = checked
    snapshot = {
        "schema_version": 3,
        "context_geometry": region["context_geometry"],
        **scope,
    }
    box = grid_box(region)
    selected = source_context_region(
        snapshot, [box[0], box[1], box[2], region["ys"][1]]
    )
    if selected is None:
        return None
    contexts = []
    names = (
        ("prefix",)
        if scope["prefix"]["origin"] == "native"
        else ("prefix", "native_prefix")
    )
    for name in names:
        packet = scope[name]
        parts = context_source_parts(packet, selected)
        if parts is None or any(
            source_claim_runs(packet, tokens=part) != (tuple(t["text"] for t in part),)
            for part in parts
        ):
            return None
        raw = "\n".join(" ".join(t["text"] for t in part) for part in parts)
        contexts.append(context_from_text("", raw))
    primary, native = contexts[0], contexts[-1]
    if not primary.table_id or any(
        getattr(native, key) and getattr(native, key) != getattr(primary, key)
        for key in ("table_id", "target", "assay", "cell_line")
    ):
        return None
    sources = [scope["prefix"]]
    if sources[0]["origin"] == "raster":
        sources.append(scope["native_prefix"])
    return (
        [{"bbox": bounds, "sources": sources}],
        bounds,
        context_from_text(prefix, prefix),
    )


def qualified_panel_context(region, prefix):
    """Keep the panel's own observed conditions, never fill them from a neighbour."""
    checked = _qualified(region, prefix)
    return checked[2] if checked is not None else None


def shared_panel_context(parent, parent_prefix, current, current_prefix):
    """Producer and saved-family replay require the same complete original facts."""
    if not isinstance(parent_prefix, str) or not isinstance(current_prefix, str):
        return False
    first, second = (
        _qualified(parent, parent_prefix),
        _qualified(current, current_prefix),
    )
    if first is None or second is None:
        return False
    try:
        validate_source_overlap(first[0], first[1], second[0], second[1])
    except ValueError:
        return False
    return True
