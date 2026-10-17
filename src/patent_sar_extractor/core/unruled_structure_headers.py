"""Original header clipping windows, explicitly not invented printed grid rules."""

import re
from itertools import pairwise

from .activity_context_geometry import valid_box
from .activity_grid_role_observation import observe_role_cells
from .caption_role_proof import observed_role
from .source_cell_tokens import cell_lines
from .source_geometry import SourceTokens
from .source_observations import source_observation_status
from .source_table_markers import TABLE_MARKER
from .source_window_chunks import observe_window_sources
from .structure_table_headers import structure_column_pairs
from .unruled_header_readings import original_header_readings

MAX_COLUMNS = 64


def header_groups(line):
    """Only nominate original separated text groups; whole-window reads decide."""
    groups = []
    for token in sorted(line, key=lambda part: part["x"]):
        box = token.get("bbox")
        if not valid_box(box):
            return []
        if groups:
            previous = groups[-1][-1]["bbox"]
            gap = box[0] - previous[2]
            height = max(box[3] - box[1], previous[3] - previous[1])
            if gap <= max(12, 2 * height):
                groups[-1].append(token)
                continue
        groups.append([token])
    return [
        {
            "text": " ".join(part["text"] for part in group),
            "bbox": [
                min(part["bbox"][0] for part in group),
                min(part["bbox"][1] for part in group),
                max(part["bbox"][2] for part in group),
                max(part["bbox"][3] for part in group),
            ],
        }
        for group in groups
    ]


def nominate_unruled_headers(tokens, page_size):
    bounds = [0, 0, *page_size]
    output = []
    for line in cell_lines(tokens, bounds):
        groups = header_groups(line)
        if 2 <= len(groups) <= MAX_COLUMNS and structure_column_pairs(
            [g["text"] for g in groups]
        ):
            output.append(groups)
    return output


def header_windows(groups, page_size):
    if not 2 <= len(groups) <= MAX_COLUMNS:
        raise ValueError("Unruled original header exceeds its column bound")
    boxes = [group["bbox"] for group in groups]
    if any(not valid_box(box) for box in boxes) or any(
        a[2] >= b[0] for a, b in pairwise(boxes)
    ):
        raise ValueError("Unruled original header columns overlap")
    xs = [0, *[(a[2] + b[0]) / 2 for a, b in pairwise(boxes)], page_size[0]]
    ys = [
        max(0, min(b[1] for b in boxes) - 4),
        min(page_size[1], max(b[3] for b in boxes) + 4),
    ]
    if not all(
        0 <= b[0] < b[2] <= page_size[0] and 0 <= b[1] < b[3] <= page_size[1]
        for b in boxes
    ):
        raise ValueError("Unruled original header leaves its page")
    return xs, ys


def observe_unruled_header(page, tokens, groups, original_pdf_sha256):
    if not isinstance(tokens, SourceTokens):
        raise TypeError("Unruled columns require original source tokens")
    size = [page.rect.width, page.rect.height]
    xs, ys = header_windows(groups, size)
    bounds = [xs[0], ys[0], xs[-1], ys[-1]]
    reading = observe_role_cells(page, {"xs": xs, "ys": ys}, tokens, retain_frames=True)
    if reading is None:
        return None
    # Retain the nearest literal table-title context, including wrapped rows.
    titles = [
        line
        for line in cell_lines(tokens, [0, 0, size[0], ys[0]])
        if TABLE_MARKER.search(" ".join(part["text"] for part in line))
    ]
    title_top = (
        max(0, min(part["bbox"][1] for part in titles[-1]) - 2) if titles else ys[0]
    )
    context_bounds = [0, title_top, size[0], ys[0]] if title_top < ys[0] else None
    return {
        "version": 1,
        "original_pdf_sha256": original_pdf_sha256,
        "page_no": page.number + 1,
        "page_size": size,
        "nomination": groups,
        "source_observations": observe_window_sources(tokens, bounds),
        "context_sources": observe_window_sources(tokens, context_bounds)
        if context_bounds
        else [],
        "role_cells": reading,
    }


def unruled_header_roles(scope):
    """Recheck original words, independent cell reads and pixel frames on replay."""
    if not isinstance(scope, dict) or set(scope) != {
        "version",
        "original_pdf_sha256",
        "page_no",
        "page_size",
        "nomination",
        "source_observations",
        "context_sources",
        "role_cells",
    }:
        raise ValueError("Malformed original unruled header scope")
    if (
        type(scope["version"]) is not int
        or scope["version"] != 1
        or type(scope["page_no"]) is not int
        or not 1 <= scope["page_no"] <= 20000
        or not isinstance(scope["original_pdf_sha256"], str)
        or not re.fullmatch(r"[a-f0-9]{64}", scope["original_pdf_sha256"])
    ):
        raise ValueError("Invalid original unruled header identity")
    size = scope["page_size"]
    if (
        not isinstance(size, list)
        or len(size) != 2
        or any(type(v) not in {int, float} or not 0 < v <= 100000 for v in size)
    ):
        raise ValueError("Invalid original unruled page frame")
    groups = scope["nomination"]
    if not isinstance(groups, list) or any(
        not isinstance(g, dict)
        or set(g) != {"text", "bbox"}
        or not isinstance(g["text"], str)
        for g in groups
    ):
        raise ValueError("Malformed original header nomination")
    xs, ys = header_windows(groups, size)
    bounds = [xs[0], ys[0], xs[-1], ys[-1]]
    sources = scope["source_observations"]
    if (
        not isinstance(sources, list)
        or not 1 <= len(sources) <= 2
        or any(
            not isinstance(p, dict)
            or source_observation_status(p, bounds, p.get("text")) == "invalid"
            for p in sources
        )
    ):
        raise ValueError("Malformed original unruled header source")
    if [source["origin"] for source in sources] not in (
        ["native"],
        ["raster", "native"],
    ):
        raise ValueError("Foreign original unruled header source order")
    observed_groups = [
        header_groups(line) for line in cell_lines(sources[0]["tokens"], bounds)
    ]
    if groups not in observed_groups:
        raise ValueError("Original unruled header nomination differs from its source")
    headers = original_header_readings(scope["role_cells"], xs, ys, sources)
    if headers is None:
        return None
    contexts = scope["context_sources"]
    if (
        not isinstance(contexts, list)
        or len(contexts) > 2
        or any(
            not isinstance(p, dict)
            or source_observation_status(p, p.get("bbox"), p.get("text")) == "invalid"
            or p["bbox"][3] != ys[0]
            or p["bbox"][0] != 0
            or p["bbox"][2] != size[0]
            for p in contexts
        )
    ):
        raise ValueError("Malformed original unruled title context")
    nonempty = [p for p in contexts if p["text"].strip()]
    role, _ = observed_role(nonempty)
    if role in {"mixed", "conflict"}:
        return None
    pairs = structure_column_pairs(headers)
    if (
        not pairs
        or any(
            not re.match(
                r"Compound|Cmpd|Cpd|Example|Ex|化合物|实施例", headers[i], re.IGNORECASE
            )
            for i, _ in pairs
        )
        and role not in {"compound", "nonfinal"}
    ):
        return None
    return {
        "headers": headers,
        "pairs": pairs,
        "xs": xs,
        "ys": ys,
        "role": "nonfinal" if role == "nonfinal" else "compound",
    }
