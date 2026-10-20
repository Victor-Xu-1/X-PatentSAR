"""Literal original corner joints shared by cell reading and grid replay."""

import math

import numpy as np

RULE_GAP_PT = 1.5
MAX_RULE_THICKNESS_PT = 2.5


def original_rule_band(mask, axis, position, lo, hi, dpi):
    """The existing bounded physical gap policy; no filled or inferred pixels."""
    extent = mask.shape[axis]
    margin = math.ceil(MAX_RULE_THICKNESS_PT * dpi / 72)
    start, end = (
        max(0, math.floor(position) - margin),
        min(extent, math.ceil(position) + margin + 1),
    )
    strip = mask[start:end, lo:hi] if axis == 0 else mask[lo:hi, start:end].T
    if not strip.size:
        return None
    maximum_gap = math.ceil(RULE_GAP_PT * dpi / 72)
    indices = []
    for index, line in enumerate(strip):
        occupied = np.flatnonzero(line)
        if (
            len(occupied)
            and max(
                int(occupied[0]),
                int(line.size - occupied[-1] - 1),
                int(np.diff(occupied).max()) - 1 if len(occupied) > 1 else 0,
            )
            <= maximum_gap
        ):
            indices.append(start + index)
    if not indices or (indices[-1] - indices[0] + 1) * 72 / dpi > MAX_RULE_THICKNESS_PT:
        return None
    return indices


def include_original_rule_joints(mask, allowed, bands):
    """Admit only an actual one-pixel join beside ink in BOTH proved rules.

    No edge dilation, paint filling or arbitrary connected-mark exclusion.
    """
    for horizontal in bands[:2]:
        rows = set(horizontal)
        for vertical in bands[2:]:
            columns = set(vertical)
            for y in range(max(0, min(rows) - 1), min(mask.shape[0], max(rows) + 2)):
                for x in range(
                    max(0, min(columns) - 1), min(mask.shape[1], max(columns) + 2)
                ):
                    if (
                        mask[y, x]
                        and any(
                            other in rows and mask[other, x] for other in (y - 1, y + 1)
                        )
                        and any(
                            other in columns and mask[y, other]
                            for other in (x - 1, x + 1)
                        )
                    ):
                        allowed[y, x] = True
