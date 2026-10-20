"""Actual closed-grid absence, preserving every nonwhite non-rule pixel."""

import math

from .cell_frame_proof import inside_box
from .plot_reference_pixels import replay_pixels
from .source_cell_pixels import (
    closed_cell_masks,
    closed_masks_are_empty,
    observe_closed_cell,
)

EMPTY_GRID_METHOD = "original_empty_grid_cell"


def valid_empty_grid_cell(reading):
    """Pure source proof only, never an activity value or inferred zero/count."""
    if (
        not isinstance(reading, dict)
        or set(reading) != {"method", "text", "bbox", "page_size", "source_pixels"}
        or reading["method"] != EMPTY_GRID_METHOD
        or reading["text"] != ""
    ):
        return False
    size = reading["page_size"]
    if (
        not isinstance(size, list)
        or len(size) != 2
        or any(
            type(v) not in (int, float) or not math.isfinite(v) or not 0 < v <= 100000
            for v in size
        )
        or not inside_box(reading["bbox"], [0, 0, *size])
    ):
        return False
    packet = reading["source_pixels"]
    if (
        not isinstance(packet, dict)
        or not isinstance(packet.get("readings"), list)
        or len(packet["readings"]) != 2
        or any(
            not isinstance(view, dict)
            or view.get("ink_mode") != "nonwhite"
            or "source_window" not in view
            for view in packet["readings"]
        )
    ):
        return False
    masks = closed_cell_masks(packet, reading["bbox"], size, content_only=True)
    return closed_masks_are_empty(masks)


def observe_empty_grid_cell(page, bounds):
    packet = observe_closed_cell(page, list(bounds), ink_mode="nonwhite")
    if packet is None:
        return None
    reading = {
        "method": EMPTY_GRID_METHOD,
        "text": "",
        "bbox": list(bounds),
        "page_size": [page.rect.width, page.rect.height],
        "source_pixels": packet,
    }
    return reading if valid_empty_grid_cell(reading) else None


def replay_empty_grid_cell(page, reading):
    if not valid_empty_grid_cell(reading) or reading["page_size"] != [
        page.rect.width,
        page.rect.height,
    ]:
        return False
    packet = reading["source_pixels"]
    for view in packet["readings"]:
        replay_pixels(page, packet["bbox"], view)
    return True
