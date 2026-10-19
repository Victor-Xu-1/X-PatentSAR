"""One caption geometry contract: ownership anchor is not its reading window."""

import math
from collections.abc import Mapping

from .caption_word_proof import WORD_FORM_METHOD

CAPTION_READ_PADDING = 4
_CELL_METHODS = {"native_cell", "page_ocr_cell", "cell_ocr_400dpi", "cell_ocr_600dpi"}


def _box(value):
    if (
        not isinstance(value, (list, tuple))
        or len(value) != 4
        or any(
            type(v) not in {int, float}
            or not 0 <= v <= 1_000_000
            or not math.isfinite(v)
            for v in value
        )
        or not value[0] < value[2]
        or not value[1] < value[3]
    ):
        return None
    return tuple(value)


def caption_read_window(anchor, page_size):
    """The original loose-caption producer and original replayer share this rule."""
    box = _box(anchor)
    if (
        box is None
        or not isinstance(page_size, (list, tuple))
        or len(page_size) != 2
        or any(
            type(v) not in {int, float}
            or not 0 < v <= 1_000_000
            or not math.isfinite(v)
            for v in page_size
        )
        or box[2] > page_size[0]
        or box[3] > page_size[1]
    ):
        raise ValueError("Invalid original caption page/anchor geometry")
    return (
        max(0, box[0] - CAPTION_READ_PADDING),
        max(0, box[1] - CAPTION_READ_PADDING),
        min(page_size[0], box[2] + CAPTION_READ_PADDING),
        min(page_size[1], box[3] + CAPTION_READ_PADDING),
    )


def caption_windows(packet):
    """Require explicit, conserved windows; never infer one from a chosen reading.

    Page-edge clipping is finally checked against the caller's actual original.
    All attempts, including weak ones, retain the same reading scope.
    """
    if not isinstance(packet, Mapping):
        return None
    anchor, reading = _box(packet.get("bbox")), _box(packet.get("reading_bbox"))
    ownership, observations = packet.get("ownership"), packet.get("observations")
    if (
        anchor is None
        or reading is None
        or not isinstance(ownership, Mapping)
        or not isinstance(observations, (list, tuple))
        or not 1 <= len(observations) <= 4
    ):
        return None
    if ownership:
        if ownership.get("kind") != "ruled_caption" or reading != anchor:
            return None
    elif (
        reading[:2]
        != (
            max(0, anchor[0] - CAPTION_READ_PADDING),
            max(0, anchor[1] - CAPTION_READ_PADDING),
        )
        or not anchor[2] <= reading[2] <= anchor[2] + CAPTION_READ_PADDING
        or not anchor[3] <= reading[3] <= anchor[3] + CAPTION_READ_PADDING
    ):
        return None
    for observation in observations:
        if not isinstance(observation, Mapping):
            return None
        method = observation.get("method")
        if not isinstance(method, str):
            return None
        if method == WORD_FORM_METHOD:
            word = observation.get("caption_word_form")
            if not isinstance(word, Mapping) or _box(word.get("bbox")) != reading:
                return None
        elif method not in _CELL_METHODS or _box(observation.get("bbox")) != reading:
            return None
    return anchor, reading


def original_caption_read_window(packet, page_size):
    windows = caption_windows(packet)
    if windows is None:
        raise ValueError("Missing or conflicting original caption reading window")
    anchor, reading = windows
    # Validate actual page clipping even for ruled cells, without expanding them.
    expanded = caption_read_window(anchor, page_size)
    if reading != (anchor if packet["ownership"] else expanded):
        raise ValueError("Original caption reading window differs from its page")
    return reading
