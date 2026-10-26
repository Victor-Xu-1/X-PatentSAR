"""Pure original title scope: whole physical cells or complete connected row ink."""

import math

from .cell_frame_proof import inside_box
from .heading_cell_source import valid_cell_geometry
from .heading_source_geometry import (
    MAX_HEADING_HEIGHT,
    NATIVE_TITLE_GAP,
    heading_bounds,
)
from .native_window_coverage import MAX_WINDOW_PAINTS, valid_native_window
from .native_window_rules import boundary_rule_path
from .source_geometry import overlaps
from .source_observations import source_observation_status


def title_seek_bounds(nomination, size):
    bounds = heading_bounds(nomination, size)
    return [0, bounds.y0, size[0], bounds.y1]


def _profile(packet, bounds):
    return (
        isinstance(packet, dict)
        and packet.get("origin") == "native"
        and (source_observation_status(packet, bounds, packet.get("text")) != "invalid")
    )


def _characters(value):
    return "".join(character for character in value if not character.isspace())


def _row_marks(row, *, cell=None):
    native, window = row["native_source"], row["window"]
    tokens = [*native["tokens"], *native["boundary_tokens"]]
    marks = [token["bbox"] for token in tokens]
    by_paint = {}
    for token in tokens:
        order = token.get("native_paint", {}).get("seqno")
        if order is not None:
            by_paint.setdefault(order, []).append(token["text"])
    for paint in window["paints"]:
        if paint["kind"] == "fill-text" and _characters(paint["text"]) == _characters(
            "".join(by_paint.get(paint["seqno"], ()))
        ):
            continue
        if (
            cell is not None
            and paint["kind"] == "stroke-path"
            and paint["rule_path"] is not None
        ):
            path = paint["rule_path"]
            for segment in path["segments"]:
                if boundary_rule_path(
                    {"width": path["width"], "segments": [segment]}, cell
                ):
                    continue
                x0, y0, x1, y1 = segment
                half = path["width"] / 2
                box = [
                    min(x0, x1) - half,
                    min(y0, y1) - half,
                    max(x0, x1) + half,
                    max(y0, y1) + half,
                ]
                if overlaps(box, window["bbox"]):
                    marks.append(box)
            continue
        marks.append(paint["bbox"])
    return marks


def _row_component(row, nomination, *, cell=None):
    window = row["window"]
    if window["refusal"] is not None:
        return None, window["refusal"]
    marks = _row_marks(row, cell=cell)
    if len(marks) > MAX_WINDOW_PAINTS:
        return None, "source_mark_budget"
    groups = []
    right = None
    for box in sorted(marks, key=lambda value: (value[0], value[2])):
        if right is not None and box[0] <= right + NATIVE_TITLE_GAP:
            groups[-1].append(box)
            right = max(right, box[2])
        else:
            groups.append([box])
            right = box[2]
    selected = [
        group for group in groups if any(overlaps(box, nomination) for box in group)
    ]
    if len(selected) != 1:
        return None, "ambiguous_title_components"
    tokens = [*row["native_source"]["tokens"], *row["native_source"]["boundary_tokens"]]
    native_boxes = {tuple(token["bbox"]) for token in tokens}
    native_groups = [
        any(tuple(box) in native_boxes for box in group) for group in groups
    ]
    if not all(native_groups):
        if sum(native_groups) != 1:
            return None, "ambiguous_unowned_title_ink"
        # Whitespace cannot discard an unrecognized role word. With one native
        # owner read the complete row; several owners remain ambiguous instead
        # of assigning orphan ink to whichever number happens to be closest.
        return [box for group in groups for box in group], None
    return selected[0], None


def _row_scope(row, nomination, size):
    fallback = list(heading_bounds(nomination, size))
    selected, refusal = _row_component(row, nomination)
    if refusal is not None:
        return fallback, refusal
    seek = title_seek_bounds(nomination, size)
    if any(not inside_box(box, seek) for box in selected):
        return fallback, "crossing_row_ink"
    boxes = [nomination, *selected]
    bounds = list(
        heading_bounds(
            [
                min(box[0] for box in boxes),
                min(box[1] for box in boxes),
                max(box[2] for box in boxes),
                max(box[3] for box in boxes),
            ],
            size,
        )
    )
    if bounds[3] - bounds[1] > MAX_HEADING_HEIGHT:
        return fallback, "title_height_budget"
    return bounds, None


def title_scope_bounds(packet, nomination, size):
    """Recompute scope from retained source facts, never a saved success flag."""
    if (
        not isinstance(size, list)
        or len(size) != 2
        or any(
            type(value) not in {int, float} or not math.isfinite(value) or value <= 0
            for value in size
        )
    ):
        return None
    if (
        not isinstance(packet, dict)
        or set(packet)
        != {
            "version",
            "method",
            "nomination_bbox",
            "page_size",
            "native_seed",
            "row_source",
            "cell_source",
        }
        or type(packet["version"]) is not int
        or packet["version"] != 1
        or packet["nomination_bbox"] != list(nomination)
        or packet["page_size"] != size
        or not isinstance(packet["page_size"], list)
        or any(type(value) not in {int, float} for value in packet["page_size"])
        or not inside_box(nomination, [0, 0, *size])
        or not _profile(packet["native_seed"], list(heading_bounds(nomination, size)))
    ):
        return None
    row = packet["row_source"]
    seek = title_seek_bounds(nomination, size)
    if (
        not isinstance(row, dict)
        or set(row) != {"native_source", "window"}
        or not _profile(row["native_source"], seek)
        or not valid_native_window(row["window"], seek)
        or row["window"]["page_size"] != size
    ):
        return None
    if packet["method"] == "closed_cell":
        cell = packet["cell_source"]
        if not valid_cell_geometry(cell, nomination, size, MAX_HEADING_HEIGHT):
            return None
        selected, refusal = _row_component(row, nomination, cell=cell["cell"])
        if refusal is not None:
            return cell["cell"], refusal
        if any(not inside_box(box, cell["cell"]) for box in selected):
            return cell["cell"], "outside_closed_title_ink"
        return cell["cell"], None
    if (
        packet["method"] != "native_row"
        or packet["cell_source"] is not None
        or not (
            packet["native_seed"]["tokens"] or packet["native_seed"]["boundary_tokens"]
        )
    ):
        return None
    return _row_scope(row, nomination, size)
