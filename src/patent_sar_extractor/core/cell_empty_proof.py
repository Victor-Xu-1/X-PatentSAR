"""Paired original absence for closed grids and complete unruled white regions."""

import math

import numpy as np

from .cell_frame_proof import inside_box
from .plot_reference_pixels import observe_pixels, replay_pixels, retained_pixels
from .source_cell_pixels import (
    MAX_CELL_PIXELS,
    closed_cell_masks,
    closed_masks_are_empty,
    observe_closed_cell,
)

EMPTY_GRID_METHOD = "original_empty_grid_cell"
EMPTY_REGION_METHOD = "original_empty_text_region"


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


def valid_empty_text_region(reading):
    """No ruling mask or noise tolerance: the complete paired rectangle is white."""
    if (
        not isinstance(reading, dict)
        or set(reading) != {"method", "text", "bbox", "page_size", "source_pixels"}
        or reading["method"] != EMPTY_REGION_METHOD
        or reading["text"] != ""
    ):
        return False
    size, bounds, packet = (
        reading["page_size"],
        reading["bbox"],
        reading["source_pixels"],
    )
    if (
        not isinstance(size, list)
        or len(size) != 2
        or any(
            type(v) not in (int, float) or not math.isfinite(v) or not 0 < v <= 100000
            for v in size
        )
        or not inside_box(bounds, [0, 0, *size])
        or not isinstance(packet, dict)
        or set(packet) != {"bbox", "readings"}
        or packet["bbox"] != bounds
        or not isinstance(packet["readings"], list)
        or len(packet["readings"]) != 2
    ):
        return False
    for view, dpi in zip(packet["readings"], (400, 600), strict=True):
        if (
            not isinstance(view, dict)
            or view.get("ink_mode") != "nonwhite"
            or not isinstance(view.get("source_window"), dict)
            or view["source_window"].get("purpose") != "pixels"
        ):
            return False
        mask = retained_pixels(view, bounds, dpi, MAX_CELL_PIXELS)
        if mask is None or np.any(mask):
            return False
    return True


def observe_empty_text_region(page, bounds):
    bounds = list(bounds)
    packet = observe_pixels(page, bounds, MAX_CELL_PIXELS, ink_mode="nonwhite")
    reading = {
        "method": EMPTY_REGION_METHOD,
        "text": "",
        "bbox": bounds,
        "page_size": [page.rect.width, page.rect.height],
        "source_pixels": packet,
    }
    return reading if valid_empty_text_region(reading) else None


def valid_empty_source(reading):
    return valid_empty_grid_cell(reading) or valid_empty_text_region(reading)


def replay_empty_source(page, reading):
    if isinstance(reading, dict) and reading.get("method") == EMPTY_GRID_METHOD:
        return replay_empty_grid_cell(page, reading)
    if not valid_empty_text_region(reading) or reading["page_size"] != [
        page.rect.width,
        page.rect.height,
    ]:
        return False
    for view in reading["source_pixels"]["readings"]:
        replay_pixels(page, reading["bbox"], view)
    return True
