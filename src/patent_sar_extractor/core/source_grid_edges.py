"""Bounded open-row windows from existing original rules, never invented edges."""

import math
import re
from itertools import pairwise

import fitz

from .role_grid_windows import role_grid_shape


def _frame_bounds(frame, page_size, has_rules):
    if frame is None and not has_rules:
        return page_size
    if (
        not isinstance(frame, dict)
        or set(frame) != {"dpi", "shape", "pixel_sha256"}
        or (
            type(frame["dpi"]) is not int
            or not 1 <= frame["dpi"] <= 1200
            or not isinstance(frame["shape"], list)
            or len(frame["shape"]) != 2
            or any(type(v) is not int or v <= 0 for v in frame["shape"])
            or frame["shape"][0] * frame["shape"][1] > 100_000_000
            or not isinstance(frame["pixel_sha256"], str)
            or not re.fullmatch(r"[a-f0-9]{64}", frame["pixel_sha256"])
        )
    ):
        raise ValueError("Invalid original grid-rule raster frame")
    pixels = (
        fitz.Rect(0, 0, *page_size) * fitz.Matrix(frame["dpi"] / 72, frame["dpi"] / 72)
    ).irect
    if frame["shape"] != [pixels.height, pixels.width]:
        raise ValueError("Original grid-rule frame differs from its page")
    return [pixels.width * 72 / frame["dpi"], pixels.height * 72 / frame["dpi"]]


def _numbers(values, size, *, increasing=False):
    return (
        isinstance(values, list)
        and len(values) == size
        and all(
            type(v) in {int, float} and -100000 <= v <= 100000 and math.isfinite(v)
            for v in values
        )
        and (not increasing or all(b > a for a, b in pairwise(values)))
    )


def edge_intervals(packet):
    """Replay nominations only; open windows never become closed grid cells."""
    if not isinstance(packet, dict) or set(packet) != {
        "version",
        "page_size",
        "xs",
        "ys",
        "vertical_rules",
        "rule_frame",
    }:
        raise ValueError("Malformed original grid-edge inventory")
    size, xs, ys, rules = (
        packet["page_size"],
        packet["xs"],
        packet["ys"],
        packet["vertical_rules"],
    )
    if (
        type(packet["version"]) is not int
        or packet["version"] != 1
        or not _numbers(size, 2)
        or not all(0 < v <= 100000 for v in size)
        or not isinstance(xs, list)
        or not 3 <= len(xs) <= 65
        or not _numbers(xs, len(xs), increasing=True)
        or not isinstance(ys, list)
        or role_grid_shape(xs, ys) is None
        or not _numbers(ys, len(ys), increasing=True)
        or not 0 <= xs[0] < xs[-1] <= size[0]
        or not 0 <= ys[0] < ys[-1] <= size[1]
        or not isinstance(rules, list)
        or len(rules) > 512
    ):
        raise ValueError("Invalid bounded original grid-edge inventory")
    rendered = _frame_bounds(packet["rule_frame"], size, bool(rules))
    if any(
        not _numbers(rule, 3)
        or not xs[0] - 8 <= rule[0] <= xs[-1] + 8
        or not 0 <= rule[1] < rule[2] <= rendered[1]
        for rule in rules
    ):
        raise ValueError("Invalid bounded original grid-edge inventory")
    output = []
    for edge, anchor in (("top", ys[0]), ("bottom", ys[-1])):
        columns = []
        for x in xs:
            matches = [
                rule
                for rule in rules
                if abs(rule[0] - x) <= 4
                and rule[1] <= anchor + 2
                and rule[2] >= anchor - 2
                and (anchor - rule[1] if edge == "top" else rule[2] - anchor) >= 12
            ]
            columns.append(matches)
        if not columns[0] or not columns[-1]:
            continue
        # Competing/coincident columns are not selected by arbitrary list order.
        confirmed = all(len(matches) == 1 for matches in columns)
        outer = [*columns[0], *columns[-1]]
        terminal = [
            rule[1 if edge == "top" else 2] for matches in columns for rule in matches
        ]
        if confirmed and max(terminal) - min(terminal) > 4:
            confirmed = False
        ends = terminal if confirmed else [r[1 if edge == "top" else 2] for r in outer]
        boundary = max(ends) if edge == "top" else min(ends)
        boundary = max(0, min(boundary, size[1]))
        if abs(boundary - anchor) < 12:
            continue
        output.append(
            {
                "edge": edge,
                "bbox": [xs[0], min(anchor, boundary), xs[-1], max(anchor, boundary)],
                "status": "observed_columns" if confirmed else "unproved_columns",
            }
        )
    return output


def original_grid_edges(page, grid):
    packet = {
        "version": 1,
        "page_size": [page.rect.width, page.rect.height],
        "xs": list(grid["xs"]),
        "ys": list(grid["ys"]),
        "vertical_rules": [list(rule) for rule in grid.get("vertical_rules", [])],
        "rule_frame": grid.get("rule_frame"),
    }
    edge_intervals(packet)
    return packet
