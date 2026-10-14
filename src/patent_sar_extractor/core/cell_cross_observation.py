"""Bounded original printed-cross observation and serialized evidence checks."""

import hashlib
import re
from itertools import pairwise

import cv2
import numpy as np


def _components(gray, threshold, dpi):
    binary = cv2.threshold(gray, threshold, 255, cv2.THRESH_BINARY_INV)[1]
    n, labels, stats, _ = cv2.connectedComponentsWithStats(binary)
    crosses = []
    for index in range(1, n):
        x, y, w, h, area = map(int, stats[index])
        if area < 8:
            continue
        component = labels[y : y + h, x : x + w] == index
        rows, columns = component.sum(axis=1), component.sum(axis=0)
        horizontal, vertical = (
            np.flatnonzero(rows >= 0.7 * w),
            np.flatnonzero(columns >= 0.7 * h),
        )
        if not len(horizontal) or not len(vertical):
            return []
        hy0, hy1 = int(horizontal[0]), int(horizontal[-1])
        vx0, vx1 = int(vertical[0]), int(vertical[-1])
        arms = np.zeros_like(component)
        arms[hy0 : hy1 + 1, :] = True
        arms[:, vx0 : vx1 + 1] = True
        cross = [
            x,
            y,
            w,
            h,
            area,
            int(rows.max()),
            int(columns.max()),
            hy0,
            hy1,
            vx0,
            vx1,
            int((component & ~arms).sum()),
        ]
        if not _shape(cross, dpi):
            return []
        crosses.append(cross)
    return sorted(crosses)


def _shape(cross, dpi):
    x, y, w, h, area, row_peak, col_peak, hy0, hy1, vx0, vx1, off_axis = cross
    return (
        1.5 <= w * 72 / dpi <= 12
        and 1.5 <= h * 72 / dpi <= 12
        and 0.5 <= w / h <= 2
        and 8 <= area < 0.7 * w * h
        and 0.7 * w <= row_peak <= w
        and 0.7 * h <= col_peak <= h
        and x >= 0
        and y >= 0
        and 0 <= hy0 <= hy1 < h
        and 0 <= vx0 <= vx1 < w
        and hy1 - hy0 + 1 <= 0.35 * h
        and vx1 - vx0 + 1 <= 0.35 * w
        and 0.3 * h <= (hy0 + hy1) / 2 <= 0.7 * h
        and 0.3 * w <= (vx0 + vx1) / 2 <= 0.7 * w
        and 0 <= off_axis <= 0.1 * area
    )


def _agree(readings, dpi, width, height):
    if not isinstance(readings, list) or len(readings) != 2:
        return False
    for reading, threshold in zip(readings, (150, 200)):
        if (
            not isinstance(reading, dict)
            or set(reading) != {"threshold", "components"}
            or type(reading["threshold"]) is not int
            or reading["threshold"] != threshold
        ):
            return False
        crosses = reading["components"]
        if not isinstance(crosses, list) or not 1 <= len(crosses) <= 3:
            return False
        if any(
            not isinstance(c, list)
            or len(c) != 12
            or any(type(v) is not int for v in c)
            or not _shape(c, dpi)
            or c[0] + c[2] > width
            or c[1] + c[3] > height
            for c in crosses
        ):
            return False
        if crosses != sorted(crosses) or any(
            a[0] + a[2] > b[0] for a, b in pairwise(crosses)
        ):
            return False
        if (
            max(c[1] + c[3] / 2 for c in crosses)
            - min(c[1] + c[3] / 2 for c in crosses)
            > dpi / 72 * 2
        ):
            return False
    first, second = (r["components"] for r in readings)
    return len(first) == len(second) and all(
        abs((a[0] + a[2] / 2) - (b[0] + b[2] / 2)) <= dpi / 72 * 0.5
        and abs((a[1] + a[3] / 2) - (b[1] + b[3] / 2)) <= dpi / 72 * 0.5
        and all(0.75 <= a[i] / b[i] <= 1.25 for i in (2, 3))
        for a, b in zip(first, second)
    )


def observe_printed_crosses(image, bounds, dpi=450):
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    readings = [
        {"threshold": t, "components": _components(gray, t, dpi)} for t in (150, 200)
    ]
    height, width = gray.shape
    value = (
        "+" * len(readings[0]["components"])
        if _agree(readings, dpi, width, height)
        else ""
    )
    return {
        "method": "printed_cross_components",
        "text": value,
        "bbox": list(bounds),
        "coordinate_space": "original_pdf_points",
        "dpi": dpi,
        "image_size": [width, height],
        "image_sha256": hashlib.sha256(image.tobytes()).hexdigest(),
        "readings": readings,
    }


def printed_cross_valid(observation, bounds, value):
    if not isinstance(bounds, (list, tuple)) or len(bounds) != 4:
        return False
    if not isinstance(observation, dict) or set(observation) != {
        "method",
        "text",
        "bbox",
        "coordinate_space",
        "dpi",
        "image_size",
        "image_sha256",
        "readings",
    }:
        return False
    size = observation["image_size"]
    return bool(
        observation["method"] == "printed_cross_components"
        and isinstance(value, str)
        and re.fullmatch(r"\+{1,3}", value)
        and observation["text"] == value
        and observation["bbox"] == list(bounds)
        and observation["coordinate_space"] == "original_pdf_points"
        and type(observation["dpi"]) is int
        and observation["dpi"] == 450
        and isinstance(size, list)
        and len(size) == 2
        and all(type(v) is int and 1 <= v <= 50000 for v in size)
        and isinstance(observation["image_sha256"], str)
        and re.fullmatch(r"[a-f0-9]{64}", observation["image_sha256"])
        and _agree(observation["readings"], 450, *size)
        and len(observation["readings"][0]["components"]) == len(value)
    )
