"""Physical ownership projection for the sole declared-text planner.

Original lines and readings are never removed. A qualified line may be consumed
by an existing coordinate source; the text planner then sees an explicit barrier,
not another copy of those measurements or a continuation through that grid.
"""

import re
from itertools import pairwise

from .activity_header_sources import context_source_parts, source_context_region
from .cell_frame_proof import inside_box
from .source_cell_tokens import cell_lines, cell_tokens
from .source_observations import source_claim_runs


def line_owner(line, regions):
    """Return a unique physical owner, never a page-wide or nearest-title guess."""
    candidates, overlaps = [], set()
    for region in regions:
        if region.get("kind") != "grid" or "grid_axes" not in region:
            continue
        if inside_box(line["bbox"], region["bbox"]):
            candidates.append({"region_id": region["region_id"], "role": "grid"})
            continue
        left, top, right, bottom = line["bbox"]
        box = region["bbox"]
        if min(right, box[2]) > max(left, box[0]) and min(bottom, box[3]) > max(
            top, box[1]
        ):
            overlaps.add(region["region_id"])
            continue
        layout = region.get("layout") or region.get("transposed_layout") or {}
        snapshot = layout.get("original_source") or layout.get("context_sources")
        caption = (layout.get("context") or {}).get("raw_caption", "")
        if not snapshot or not caption or caption.split() != line["text"].split():
            continue
        axes = region["grid_axes"]
        xs, ys = axes["xs"], axes["ys"]
        start = layout.get("data_start", layout.get("header_row", -1) + 1)
        if start <= 0:
            continue
        band = [xs[0], ys[0], xs[-1], ys[start]]
        scoped = source_context_region(snapshot, band)
        if scoped is None:
            continue
        packet = snapshot["prefix"]
        parts = context_source_parts(packet, scoped)
        if parts is None:
            continue
        tokens = cell_tokens([token for part in parts for token in part], line["bbox"])
        if (
            tokens
            and " ".join(token["text"] for token in tokens).split()
            == line["text"].split()
            and all(inside_box(token["bbox"], line["bbox"]) for token in tokens)
            and source_claim_runs(packet, tokens=tokens)
            == (tuple(token["text"] for token in tokens),)
        ):
            candidates.append({"region_id": region["region_id"], "role": "caption"})
    if overlaps or len(candidates) > 1:
        return {
            "role": "ambiguous",
            "region_ids": sorted(
                overlaps | {candidate["region_id"] for candidate in candidates}
            ),
        }
    return candidates[0] if candidates else None


def owned(line):
    owner = line.get("coordinate_owner")
    return isinstance(owner, dict) and owner.get("role") in ("grid", "caption")


def annotations_match(source, regions, qualified):
    """A saved owner flag is not authority; recompute from the actual inventory."""
    if (
        not isinstance(source, dict)
        or not isinstance(source.get("lines"), list)
        or len(source["lines"]) > 4096
        or any(not isinstance(line, dict) for line in source["lines"])
    ):
        return False
    for line in source["lines"]:
        expected = line_owner(line, regions) if qualified(line) else None
        if line.get("coordinate_owner") != expected:
            return False
    return True


def _presentation(source):
    if source["origin"] == "native":
        text = source["nomination_text"]
        words = list(re.finditer(r"\S+", text))
        cursor, spans, positions = 0, [], []
        for line in source["lines"]:
            parts = line["nomination"].split()
            selected = words[cursor : cursor + len(parts)]
            if [word.group() for word in selected] != parts:
                return text, [], []  # Complete-source qualification still refuses.
            if selected:
                positions.append((line, selected[0].start(), selected[-1].end()))
            if selected and owned(line):
                spans.append((selected[0].start(), selected[-1].end()))
            cursor += len(parts)
        return (text, spans, positions) if cursor == len(words) else (text, [], [])
    tokens = [
        {
            **line,
            "x": (line["bbox"][0] + line["bbox"][2]) / 2,
            "y": (line["bbox"][1] + line["bbox"][3]) / 2,
        }
        for line in source["lines"]
    ]
    pieces, spans, positions, offset = [], [], [], 0
    for row_no, row in enumerate(cell_lines(tokens, [0, 0, *source["page_size"]])):
        if row_no:
            pieces.append("\n")
            offset += 1
        for column, line in enumerate(row):
            if column:
                pieces.append(" ")
                offset += 1
            text = line["text"]
            positions.append((line, offset, offset + len(text)))
            if owned(line):
                spans.append((offset, offset + len(text)))
            pieces.append(text)
            offset += len(text)
    return "".join(pieces), spans, positions


def _physical_barriers(positions):
    """Extraction order cannot bridge an intervening physical grid.

    Keep native order verbatim; do not sort columns into an invented reading
    order. A proved grid between two outside lines is an additional boundary,
    including when PDF object insertion put the grid earlier in the text stream.
    """
    bodies, outside = {}, []
    for line, start, end in positions:
        owner = line.get("coordinate_owner")
        if owned(line) and owner["role"] == "grid":
            box = line["bbox"]
            previous = bodies.get(owner["region_id"], box)
            bodies[owner["region_id"]] = [
                min(previous[0], box[0]),
                min(previous[1], box[1]),
                max(previous[2], box[2]),
                max(previous[3], box[3]),
            ]
        elif not owned(line):
            outside.append((line, start, end))
    for (before, _, start), (after, end, _) in pairwise(outside):
        first, second = before["bbox"], after["bbox"]
        if start < end and any(
            (
                first[3] <= box[1] < box[3] <= second[1]
                or second[3] <= box[1] < box[3] <= first[1]
            )
            and min(first[2], box[2]) > max(first[0], box[0])
            and min(second[2], box[2]) > max(second[0], box[0])
            for box in bodies.values()
        ):
            yield start, end


def text_partition(source):
    """Preserve original character positions; owned text is an explicit barrier."""
    text, spans, positions = _presentation(source)
    spans.extend(_physical_barriers(positions))
    merged = []
    for start, end in sorted(spans):
        if merged and not text[merged[-1][1] : start].strip():
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    projected = list(text)
    for start, end in merged:
        for index in range(start, end):
            if not projected[index].isspace():
                projected[index] = " "
    return "".join(projected), merged


def validate_barriers(barriers, text):
    if not isinstance(barriers, (list, tuple)) or len(barriers) > 4096:
        raise ValueError("Original coordinate/text partition exceeds its bound")
    previous = 0
    for span in barriers:
        if (
            not isinstance(span, (list, tuple))
            or len(span) != 2
            or any(type(value) is not int for value in span)
            or not previous <= span[0] < span[1] <= len(text)
            or text[span[0] : span[1]].strip()
        ):
            raise ValueError("Malformed original coordinate/text partition")
        previous = span[1]
