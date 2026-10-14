"""Re-read overlapping detector fragments as one physically owned text line."""

import math
from itertools import combinations

import cv2

from .cell_line_coverage import complete_line_bounds
from .cell_ocr_scores import confidence_score


def bounds(part):
    points = part["bbox"]
    return (
        min(p[0] for p in points),
        min(p[1] for p in points),
        max(p[0] for p in points),
        max(p[1] for p in points),
    )


def _same_line(a, b):
    left, right = bounds(a), bounds(b)
    overlap = min(left[3], right[3]) - max(left[1], right[1])
    height = min(left[3] - left[1], right[3] - right[1])
    return height > 0 and overlap >= 0.5 * height


def resolve_overlapping_lines(
    image, parts, engine, border, *, complete_lines=False, dpi=400
):
    """No string overlap/ID guessing: only observed intersecting line boxes.

    Normal non-overlapping detections are untouched. At most eight line crops
    are recognized through the same existing engine; original detections remain
    available to the caller. Bounds are clipped to the same cell-owned image.
    """
    groups = []
    for part in sorted(parts, key=lambda p: (bounds(p)[1], bounds(p)[0])):
        owners = [g for g in groups if any(_same_line(part, old) for old in g)]
        if (
            len(owners) > 1
            or owners
            and not all(_same_line(part, old) for old in owners[0])
        ):
            # A tall cross-line fragment has no unique physical line owner.
            return None
        if owners:
            owners[0].append(part)
        else:
            groups.append([part])
    if len(groups) > 8 or len(parts) > 32:
        return None
    resolved = []
    for group in groups:
        boxes = [bounds(part) for part in group]
        overlaps = any(
            min(a[2], b[2]) - max(a[0], b[0]) > 1 for a, b in combinations(boxes, 2)
        )
        try:
            complete = (
                complete_line_bounds(image, boxes, border, dpi)
                if complete_lines
                else None
            )
        except (ValueError, TypeError, OverflowError):
            return None
        if not overlaps and complete is None:
            resolved.extend(sorted(group, key=lambda p: bounds(p)[0]))
            continue
        x0, y0 = (
            max(0, math.floor(min(b[0] for b in boxes))),
            max(0, math.floor(min(b[1] for b in boxes))),
        )
        x1, y1 = (
            min(image.shape[1], math.ceil(max(b[2] for b in boxes))),
            min(image.shape[0], math.ceil(max(b[3] for b in boxes))),
        )
        if complete is not None:
            x0, y0, x1, y1 = complete
        if x1 <= x0 or y1 <= y0:
            return None
        clip = cv2.copyMakeBorder(
            image[y0:y1, x0:x1],
            border,
            border,
            border,
            border,
            cv2.BORDER_CONSTANT,
            value=(255, 255, 255),
        )
        result, _ = engine(clip, use_det=False, use_cls=False)
        if len(result or []) != 1:
            return None
        try:
            if len(result[0]) != 2 or not isinstance(result[0][0], str):
                return None
            confidence = confidence_score(result[0][1])
        except (TypeError, ValueError, OverflowError):
            return None
        resolved.append(
            {
                "text": str(result[0][0]),
                "confidence": confidence
                if math.isfinite(confidence) and 0 <= confidence <= 1
                else 0.0,
                "bbox": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]],
                "coordinate_space": "cell_ink_crop_pixels",
                "method": "complete_line_recognition"
                if complete is not None
                else "overlapping_line_recognition",
            }
        )
    return resolved
