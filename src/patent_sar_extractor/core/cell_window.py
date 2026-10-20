"""Lossless cell-window geometry; no OCR, text interpretation or paint masking."""

import math
from dataclasses import dataclass

import cv2
import numpy as np

from .cell_rule_pixels import (
    MAX_RULE_THICKNESS_PT,
    include_original_rule_joints,
    original_rule_band,
)


@dataclass(frozen=True)
class CellWindow:
    """A source-pixel rectangle and an optional isolated closed frame witness."""

    bounds: tuple[int, int, int, int]
    frame_strips: tuple[int, int, int, int] | None = None

    def view(self, image: np.ndarray) -> np.ndarray:
        x0, y0, x1, y1 = self.bounds
        return image[y0:y1, x0:x1]


def proposed_cell_window(
    image: np.ndarray, dpi: int, *, allow_text_frame: bool = False
) -> CellWindow:
    """Propose a complete literal frame, not permission to crop connected ink.

    A fixed inset is not a content boundary. Only four proved straight edge
    bodies and their literal original one-pixel corner joints may be excluded.
    Every excluded pixel must lie in proved rule bands/joints. The selector
    separately requires disconnection or same-original paired support. The
    existing bounded grid-gap policy also
    supports literal dashed rules without filling them. Unsupported/open edge
    bodies, attached glyphs and thick frames retain the source unchanged.

    Non-white pixels, including faint antialiasing, participate in conservation.
    The bounded strip thickness limits geometry, not an OCR confidence filter.
    This selector alone is NOT an identifier/role/measurement acceptance proof.
    """
    if (
        not isinstance(image, np.ndarray)
        or image.ndim != 3
        or image.shape[2] != 3
        or image.dtype != np.uint8
        or image.shape[0] <= 0
        or image.shape[1] <= 0
        or image.shape[0] * image.shape[1] > 8_000_000
        or type(dpi) is not int
        or not 1 <= dpi <= 1200
        or type(allow_text_frame) is not bool
    ):
        raise ValueError("Invalid bounded original cell pixels")
    height, width = image.shape[:2]
    complete = CellWindow((0, 0, width, height))
    # A chemical ring, diagram or plot can have exactly the same geometry.
    # Only a text-owned caller may consider frame removal. Unknown/pixel
    # callers always retain the complete source, even for a perfect rectangle.
    if not allow_text_frame:
        return complete
    foreground = np.any(image != 255, axis=2)
    occupied_rows = np.flatnonzero(foreground.any(axis=1))
    if not len(occupied_rows):
        return complete
    occupied_columns = np.flatnonzero(foreground.any(axis=0))
    x0, x1 = int(occupied_columns[0]), int(occupied_columns[-1]) + 1
    y0, y1 = int(occupied_rows[0]), int(occupied_rows[-1]) + 1
    source = foreground[y0:y1, x0:x1]
    maximum = math.ceil(dpi * MAX_RULE_THICKNESS_PT / 72) + 1
    if min(source.shape) <= 2 * maximum + 3:
        return complete
    # Straight edge bodies are independent of miter/antialias corner pixels.
    # The excluded component is checked in full below, not inferred from a
    # smoothed line or a repaired/filled gap.
    height, width = source.shape
    bands = [
        original_rule_band(source, 0, 0, 0, width, dpi),
        original_rule_band(source, 0, height - 1, 0, width, dpi),
        original_rule_band(source, 1, 0, 0, height, dpi),
        original_rule_band(source, 1, width - 1, 0, height, dpi),
    ]
    if any(band is None for band in bands):
        return complete
    top, bottom, left, right = (
        max(bands[0]) + 1,
        height - min(bands[1]),
        max(bands[2]) + 1,
        width - min(bands[3]),
    )
    strips = (left, top, right, bottom)
    if (
        not all(0 < thickness <= maximum for thickness in strips)
        or source.shape[1] - left - right < 3
        or source.shape[0] - top - bottom < 3
    ):
        return complete
    interior = source[top : source.shape[0] - bottom, left : source.shape[1] - right]
    # A bare rectangle could be a chemical ring, not an empty table cell.
    # This geometry utility cannot assign that role or declare a missing value.
    if not interior.any():
        return complete
    # Every excluded pixel must belong to a proved rule body or literal joint.
    # This is a PROPOSAL only; contact separation still needs independent proof.
    excluded = source.copy()
    excluded[top : source.shape[0] - bottom, left : source.shape[1] - right] = False
    allowed = np.zeros_like(source)
    for band in bands[:2]:
        allowed[band, :] = True
    for band in bands[2:]:
        allowed[:, band] = True
    include_original_rule_joints(source, allowed, bands)
    if np.any(excluded & ~allowed):
        return complete
    return CellWindow((x0 + left, y0 + top, x1 - right, y1 - bottom), strips)


def observe_cell_windows(image, dpi, *, allow_text_frame=False):
    """One rule inventory gives both the selected view and bounded proposal."""
    proposed = proposed_cell_window(image, dpi, allow_text_frame=allow_text_frame)
    if proposed.frame_strips is None:
        return proposed, proposed
    x0, y0, x1, y1 = proposed.bounds
    source = np.any(image != 255, axis=2)
    _, labels = cv2.connectedComponents(source.astype(np.uint8), connectivity=8)
    excluded = source.copy()
    excluded[y0:y1, x0:x1] = False
    components = np.unique(labels[excluded])
    if not len(components) or np.any(components == 0):
        return CellWindow((0, 0, image.shape[1], image.shape[0])), proposed
    if np.any(
        np.isin(
            labels[y0:y1, x0:x1],
            components,
        )
    ):
        return CellWindow((0, 0, image.shape[1], image.shape[0])), proposed
    return proposed, proposed


def select_cell_window(image, dpi, *, allow_text_frame=False):
    """Select only disconnected frames; a proposal alone never authorizes a cut."""
    return observe_cell_windows(image, dpi, allow_text_frame=allow_text_frame)[0]
