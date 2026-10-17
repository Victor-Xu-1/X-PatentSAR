"""Literal header/caption clipping domains, explicitly not printed grid facts."""

from itertools import pairwise

from .activity_context_geometry import MAX_TABLES
from .source_cell_tokens import cell_lines
from .source_table_captions import table_caption_nominees
from .structure_table_headers import header_groups, structure_column_pairs

MAX_COLUMNS = 64


def _preceding_captions(captions, top):
    # Vertical alignment is not a scientific ownership condition. Every
    # complete literal title in the same bounded prefix remains a candidate;
    # crossing/conflicting positions cannot authorize a partition.
    return [
        c for c in captions if max(0, top - 310) <= c["bbox"][1] < c["bbox"][3] <= top
    ]


def header_partitions(groups, captions, size, top):
    """Explicit independently positioned titles may divide one original row."""
    if len(captions) > MAX_TABLES:
        raise ValueError("Original logical title inventory exceeds its bound")
    whole = {"groups": groups, "selection": [0, len(groups)], "band": [0, size[0]]}
    row = [c["bbox"] for c in _preceding_captions(captions, top)]
    positions = []
    for box in sorted(row):
        if positions and abs(box[0] - positions[-1][0]) <= 4:
            previous = positions[-1]
            positions[-1] = [
                min(previous[0], box[0]),
                min(previous[1], box[1]),
                max(previous[2], box[2]),
                max(previous[3], box[3]),
            ]
        else:
            positions.append(box)
    if len(positions) < 2 or any(a[2] >= b[0] for a, b in pairwise(positions)):
        return [whole]
    edges = [0, *[box[0] for box in positions[1:]], size[0]]
    result, covered = [], 0
    for left, right in pairwise(edges):
        selected = [
            i
            for i, g in enumerate(groups)
            if left <= g["bbox"][0] < g["bbox"][2] <= right
        ]
        if not selected:
            continue
        start, end = selected[0], selected[-1] + 1
        if selected != list(range(start, end)) or not structure_column_pairs(
            [g["text"] for g in groups[start:end]]
        ):
            return [whole]
        covered += len(selected)
        result.append(
            {"groups": groups, "selection": [start, end], "band": [left, right]}
        )
    return result if covered == len(groups) else [whole]


def caption_logical_band(caption, captions, nominations, size):
    """Independent declarations reuse the same literal title/header partition."""
    bands = set()
    for nomination in nominations:
        top = max(0, min(g["bbox"][1] for g in nomination["groups"]) - 4)
        left, right = nomination["band"]
        if (
            nomination["band"] != [0, size[0]]
            and caption in _preceding_captions(captions, top)
            and left <= caption["bbox"][0] < right
        ):
            bands.add((left, right))
    return list(next(iter(bands))) if len(bands) == 1 else None


def nomination_groups(nomination):
    start, end = nomination["selection"]
    return nomination["groups"][start:end]


def context_captions(contexts, size):
    return [
        caption
        for packet in contexts
        for caption in table_caption_nominees(packet["tokens"], size)
    ]


def nominate_unruled_headers(tokens, page_size, *, native_tokens=()):
    bounds, output = [0, 0, *page_size], []
    captions = table_caption_nominees(tokens, page_size, native_tokens=native_tokens)
    for line in cell_lines(tokens, bounds):
        groups = header_groups(line)
        if 2 <= len(groups) <= MAX_COLUMNS and structure_column_pairs(
            [g["text"] for g in groups]
        ):
            top = max(0, min(g["bbox"][1] for g in groups) - 4)
            partitions = header_partitions(groups, captions, page_size, top)
            if len(output) + len(partitions) > MAX_TABLES:
                raise ValueError("Original logical column inventory exceeds its bound")
            output.extend(partitions)
    return output
