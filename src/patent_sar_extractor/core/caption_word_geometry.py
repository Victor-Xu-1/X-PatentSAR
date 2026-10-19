"""Two complete original ink words, not OCR-dependent character repair."""

import math

import numpy as np

MAX_CAPTION_WORD_PIXELS = 1_000_000
MAX_CAPTION_WORD_PARTITIONS = 4


def caption_word_partitions(mask, dpi):
    if (
        type(dpi) is not int
        or dpi not in {400, 600}
        or not isinstance(mask, np.ndarray)
        or mask.ndim != 2
        or mask.size > MAX_CAPTION_WORD_PIXELS
        or not np.all((mask == 0) | (mask == 1))
    ):
        return None
    rows = np.flatnonzero(mask.any(axis=1))
    if (
        not len(rows)
        or rows[-1] - rows[0] + 1 > 12 * dpi / 72
        or np.any(np.diff(rows) > max(1, math.ceil(dpi / 72 * 0.7)))
    ):
        return None
    top, bottom = int(rows[0]), int(rows[-1]) + 1
    columns = np.flatnonzero(mask.any(axis=0))
    # Narrow characters can leave gaps as wide as a word space. Keep EVERY
    # bounded candidate partition; only literal full/word evidence may resolve
    # one. Excess partitions refuse, never truncate to a preferred cut.
    gaps = np.diff(columns) - 1
    cuts = np.flatnonzero(gaps >= max(3, math.ceil((bottom - top) / 6)))
    if not 1 <= len(cuts) <= MAX_CAPTION_WORD_PARTITIONS:
        return None
    result = []
    for split in cuts:
        boxes = []
        for left, right in (
            (int(columns[0]), int(columns[split]) + 1),
            (int(columns[split + 1]), int(columns[-1]) + 1),
        ):
            occupied = np.flatnonzero(mask[:, left:right].any(axis=1))
            boxes.append([left, int(occupied[0]), right, int(occupied[-1]) + 1])
        result.append(boxes)
    return result
