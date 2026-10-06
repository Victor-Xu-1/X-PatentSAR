"""Bounded existing visible-label crop tasks, separate from identity and OCR."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _visible_label_crop_tasks_from_page_image(
    struct: dict, include_wide: bool = True
) -> list[tuple[str, Any]]:
    raw = struct.get("struct") or {}
    bbox = raw.get("bbox") or []
    if len(bbox) != 4:
        return []

    image_path = str(struct.get("image_path") or "")
    if not image_path:
        return []
    page_no = int(struct.get("page_no") or 0)
    page_image = Path(image_path).with_name(f"page_{page_no:03d}.png")
    if not page_image.is_file():
        return []

    try:
        from PIL import Image, ImageEnhance, ImageOps
    except (ImportError, OSError):
        return []

    try:
        img = Image.open(page_image).convert("L")
        x0, y0, x1, y1 = [round(float(v)) for v in bbox]
    except (OSError, TypeError, ValueError, OverflowError):
        return []

    width = max(1, x1 - x0)
    height = max(1, y1 - y0)
    strict_boxes = [
        (
            x0 + int(0.25 * width),
            y1 - int(0.05 * height),
            x1 - int(0.25 * width),
            y1 + max(16, int(0.16 * height)),
        ),
        (x0 + int(0.25 * width), y0 + int(0.70 * height), x1 - int(0.25 * width), y1),
        (
            x0 + int(0.35 * width),
            y1 - int(0.02 * height),
            x1 - int(0.35 * width),
            y1 + max(20, int(0.18 * height)),
        ),
    ]
    normal_boxes = [
        (
            x0 + int(0.18 * width),
            y0 + int(0.58 * height),
            x1 - int(0.18 * width),
            y1 + max(8, int(0.10 * height)),
        ),
        (
            x0 + int(0.05 * width),
            y0 + int(0.52 * height),
            x1 - int(0.05 * width),
            y1 + max(18, int(0.22 * height)),
        ),
    ]
    wide_boxes = (
        [
            (x0, y0 + int(0.45 * height), x1, y1 + max(28, int(0.32 * height))),
            (
                x0 + int(0.10 * width),
                y0 + int(0.35 * height),
                x1 - int(0.10 * width),
                y1 + max(36, int(0.38 * height)),
            ),
        ]
        if include_wide
        else []
    )

    tasks: list[tuple[str, Any]] = []
    source_boxes = [("page_strict", strict_boxes)]
    if include_wide:
        source_boxes.append(("page_wide", normal_boxes + wide_boxes))
    for source, boxes in source_boxes:
        for box in boxes:
            left = max(0, box[0])
            top = max(0, box[1])
            right = min(img.width, box[2])
            bottom = min(img.height, box[3])
            if right - left <= 5 or bottom - top <= 5:
                continue
            try:
                crop = img.crop((left, top, right, bottom))
                crop = ImageOps.autocontrast(crop)
                crop = crop.resize((crop.width * 3, crop.height * 3))
                crop = ImageEnhance.Sharpness(crop).enhance(2.0)
            except (OSError, TypeError, ValueError, OverflowError) as exc:
                logger.debug("Visible-label crop was not readable: %s", exc)
                continue
            tasks.append((source, crop))
    return tasks


def _visible_label_crop_tasks_from_structure_image(
    struct: dict,
) -> list[tuple[str, Any]]:
    image_path = str(struct.get("image_path") or "")
    if not image_path or not os.path.exists(image_path):
        return []
    try:
        from PIL import Image
    except (ImportError, OSError):
        return []
    try:
        img = Image.open(image_path).convert("L")
        width, height = img.size
        return [
            ("direct", img.crop((0, int(height * 0.72), width, height))),
            (
                "direct",
                img.crop(
                    (int(width * 0.15), int(height * 0.62), int(width * 0.85), height)
                ),
            ),
        ]
    except (OSError, TypeError, ValueError, OverflowError):
        return []
