"""Re-read overlapping detector fragments as one physically owned text line."""

import math
from itertools import combinations

import cv2

from .cell_line_coverage import complete_line_bounds
from .cell_ocr_line_groups import bounds, group_text_lines
from .cell_ocr_scores import confidence_score


def resolve_overlapping_lines(
    image, parts, engine, border, *, complete_lines=False, dpi=400
):
    """Observe overlapping or fragmented caption rows, never join identifier text.

    Non-caption non-overlapping detections are untouched. At most eight line
    crops use the same existing engine; original detections remain available.
    Every crop stays inside the same cell-owned image.
    """
    groups = group_text_lines(parts)
    if groups is None:
        return None
    resolved = []
    for group in groups:
        boxes = [bounds(part) for part in group]
        overlaps = any(
            min(a[2], b[2]) - max(a[0], b[0]) > 1 for a, b in combinations(boxes, 2)
        )
        try:
            complete = (
                complete_line_bounds(
                    image, boxes, border, dpi, fragmented=len(group) > 1
                )
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
