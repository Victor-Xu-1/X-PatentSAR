"""Complete bounded native/raster source windows, without an OCR or writer."""

import json
from itertools import pairwise

from .activity_context_geometry import valid_box
from .source_cell_tokens import cell_lines, cell_tokens
from .source_geometry import native_region
from .source_observations import (
    project_source_observation,
    source_cell_observation,
    source_observation_status,
)


def window_chunks(tokens, window):
    members = {}
    for source_index, source in enumerate(
        (tokens, getattr(tokens, "native_tokens", []))
    ):
        for token in source:
            _, counts = members.setdefault(id(token), (token, [0, 0]))
            counts[source_index] += 1
    rows = cell_lines([token for token, _ in members.values()], window)
    cuts, count = [window[1]], [0, 0]
    for index, row in enumerate(rows):
        row_count = [
            sum(members[id(token)][1][source] for token in row) for source in (0, 1)
        ]
        if max(row_count) > 384:
            raise ValueError("Original boundary context row exceeds its token bound")
        if any(count[source] + row_count[source] > 384 for source in (0, 1)):
            cut = (max(t["y"] for t in rows[index - 1]) + min(t["y"] for t in row)) / 2
            if not cuts[-1] < cut < window[3]:
                raise ValueError("Unproved original boundary-context partition")
            cuts.append(cut)
            count = [0, 0]
        count = [count[source] + row_count[source] for source in (0, 1)]
    cuts.append(window[3])
    if len(cuts) > 513:
        raise ValueError("Original boundary context exceeds its chunk bound")
    return [[window[0], y0, window[2], y1] for y0, y1 in pairwise(cuts)]


def observe_window_sources(tokens, bounds):
    native = native_region(tokens, bounds, False)
    sources = [source_cell_observation(tokens, bounds, native=native)]
    if not native:
        sources.append(source_cell_observation(tokens, bounds, native=True))
    return sources


def observe_source_window(tokens, window):
    return [
        {"bbox": box, "sources": observe_window_sources(tokens, box)}
        for box in window_chunks(tokens, window)
    ]


def window_source_tokens(chunks, bounds, *, native=False):
    """Project retained facts only; caller first validates the complete parent."""
    selected = []
    for chunk in chunks:
        source = (
            next(p for p in chunk["sources"] if p["origin"] == "native")
            if native
            else chunk["sources"][0]
        )
        selected.extend(cell_tokens(source["tokens"], bounds))
    return selected


def _canonical_tokens(parts):
    return sorted(json.dumps(p, sort_keys=True, allow_nan=False) for p in parts)


def source_packet_projection(packet, chunks, bounds):
    expected = window_source_tokens(chunks, bounds, native=packet["origin"] == "native")
    return _canonical_tokens(packet["tokens"]) == _canonical_tokens(expected)


def validate_source_projection(chunks, bounds, parent_chunks, parent_bounds):
    """A child cannot drop or invent facts from its validated complete parent."""
    validate_source_window(chunks, bounds)
    if not (
        parent_bounds[0] <= bounds[0] < bounds[2] <= parent_bounds[2]
        and parent_bounds[1] <= bounds[1] < bounds[3] <= parent_bounds[3]
    ):
        raise ValueError("Original source projection leaves its complete context")
    for chunk in chunks:
        for source in chunk["sources"]:
            if not source_packet_projection(source, parent_chunks, chunk["bbox"]):
                raise ValueError(
                    "Original source projection differs from complete context"
                )


def validate_source_overlap(chunks, bounds, other_chunks, other_bounds):
    """Retained overlapping page contexts must conserve the same original facts."""
    validate_source_window(chunks, bounds)
    validate_source_window(other_chunks, other_bounds)
    overlap = [
        max(bounds[0], other_bounds[0]),
        max(bounds[1], other_bounds[1]),
        min(bounds[2], other_bounds[2]),
        min(bounds[3], other_bounds[3]),
    ]
    if not valid_box(overlap):
        raise ValueError("Original source contexts have no common region")
    selected = project_source_window(chunks, bounds, overlap)
    validate_source_projection(selected, overlap, other_chunks, other_bounds)


def project_source_window(chunks, bounds, window):
    """Clip a validated retained window without another source read or store."""
    validate_source_window(chunks, bounds)
    if not (
        valid_box(window)
        and bounds[0] <= window[0] < window[2] <= bounds[2]
        and bounds[1] <= window[1] < window[3] <= bounds[3]
    ):
        raise ValueError("Original source projection leaves its complete context")
    selected = []
    for chunk in chunks:
        clip = [
            window[0],
            max(window[1], chunk["bbox"][1]),
            window[2],
            min(window[3], chunk["bbox"][3]),
        ]
        if valid_box(clip):
            selected.append(
                {
                    "bbox": clip,
                    "sources": [
                        project_source_observation(p, clip) for p in chunk["sources"]
                    ],
                }
            )
    return selected


def validate_source_window(chunks, window, *, allow_legacy=False):
    if (
        not valid_box(window)
        or not isinstance(chunks, list)
        or not 1 <= len(chunks) <= 512
    ):
        raise ValueError("Malformed original source-window inventory")
    bottom = window[1]
    for chunk in chunks:
        if not isinstance(chunk, dict) or set(chunk) != {"bbox", "sources"}:
            raise ValueError("Invalid original boundary-context chunk")
        box, sources = chunk["bbox"], chunk["sources"]
        if (
            not valid_box(box)
            or not isinstance(box, list)
            or box[0] != window[0]
            or box[2] != window[2]
            or not bottom == box[1] < box[3] <= window[3]
            or not isinstance(sources, list)
            or not 1 <= len(sources) <= 2
        ):
            raise ValueError("Omitted or overlapping original context window")
        bottom = box[3]
        origins = []
        for observed in sources:
            if observed is None and allow_legacy:
                origins.append(None)
                continue
            if (
                not isinstance(observed, dict)
                or source_observation_status(observed, box, observed.get("text"))
                == "invalid"
            ):
                raise ValueError("Invalid original context coordinates or confidence")
            origins.append(observed["origin"])
        if origins not in (["native"], ["raster", "native"]) and not (
            allow_legacy and origins == [None, None]
        ):
            raise ValueError("Foreign original source-window origin")
    if bottom != window[3]:
        raise ValueError("Incomplete original boundary-context coverage")
