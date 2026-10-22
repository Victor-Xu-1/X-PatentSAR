"""Only literal edges of the caller's already-proved original content frame."""

import numpy as np

from .cell_rule_pixels import include_original_rule_joints, original_rule_band
from .reaction_arrows import contained
from .reaction_vectors import valid_rectangle


def frame_ink(source, mask, origin, dpi):
    frame, bounds = source["frame"], source["bounds"]
    if frame is None:
        return None, []
    if (
        not valid_rectangle(frame, source["page_size"])
        or not contained(bounds, frame)
        or bounds[0] != frame[0]
        or bounds[2] != frame[2]
    ):
        raise ValueError("Pixel reaction frame differs from its original declaration")
    scale = dpi / 72
    allowed = np.zeros_like(mask, dtype=bool)
    horizontal, vertical, boxes = [], [], []

    def edge(axis, coordinate):
        # Mask axis0 indexes Y rows; geometric origins are stored [X,Y].
        position = (coordinate - origin[1 - axis]) * scale
        indices = original_rule_band(mask, axis, position, 0, mask.shape[1 - axis], dpi)
        if indices is None:
            # The already-proved enclosing rule may lie outside this inner
            # content clip. Authorize NO pixels here without a literal witness;
            # every unclaimed fragment remains normal unknown source ink.
            return
        if axis == 0:
            allowed[indices, :] = mask[indices, :]
            boxes.append(
                [
                    origin[0],
                    origin[1] + min(indices) / scale,
                    origin[0] + mask.shape[1] / scale,
                    origin[1] + (max(indices) + 1) / scale,
                ]
            )
            horizontal.append(indices)
        else:
            allowed[:, indices] = mask[:, indices]
            boxes.append(
                [
                    origin[0] + min(indices) / scale,
                    origin[1],
                    origin[0] + (max(indices) + 1) / scale,
                    origin[1] + mask.shape[0] / scale,
                ]
            )
            vertical.append(indices)

    edge(1, frame[0])
    edge(1, frame[2])
    if bounds[1] == frame[1]:
        edge(0, frame[1])
    if bounds[3] == frame[3]:
        edge(0, frame[3])
    if horizontal:
        before = allowed.copy()
        include_original_rule_joints(
            mask, allowed, [horizontal[0], horizontal[-1], *vertical]
        )
        y, x = np.nonzero(allowed & ~before)
        if len(x) > 256:
            raise ValueError("Original reaction frame joint bound exceeded")
        boxes.extend(
            [
                origin[0] + px / scale,
                origin[1] + py / scale,
                origin[0] + (px + 1) / scale,
                origin[1] + (py + 1) / scale,
            ]
            for px, py in zip(x.tolist(), y.tolist(), strict=True)
        )
    return allowed, boxes
