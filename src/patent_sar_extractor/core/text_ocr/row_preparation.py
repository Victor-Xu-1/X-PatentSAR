"""Bounded blank-padding views over one unchanged complete original ink row."""

import re

import cv2
import numpy as np

from patent_sar_extractor.core.cell_text_row_readings import row_recognition_border

from .protocol import MAX_PIXELS, frame_digest


def row_frame(image):
    digest = frame_digest(image)
    ys, xs = np.where(cv2.cvtColor(image, cv2.COLOR_RGB2GRAY) < 180)
    if not len(xs):
        raise ValueError("Auxiliary row has no complete original ink")
    crop = [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1]
    frame = {
        "source_shape": list(image.shape),
        "source_pixel_sha256": digest,
        "ink_crop_pixels": crop,
        "border_pixels": crop[0],
    }
    compact = checked_frame(frame)
    if compact is None:
        return frame, None
    x0, y0, x1, y1 = crop
    alternate = cv2.copyMakeBorder(
        image[y0:y1, x0:x1],
        compact,
        compact,
        compact,
        compact,
        cv2.BORDER_CONSTANT,
        value=(255, 255, 255),
    )
    frame_digest(alternate)
    return frame, alternate


def checked_frame(frame):
    if not isinstance(frame, dict) or set(frame) != {
        "source_shape",
        "source_pixel_sha256",
        "ink_crop_pixels",
        "border_pixels",
    }:
        raise ValueError("Malformed auxiliary row preparation")
    shape, crop, border = (
        frame["source_shape"],
        frame["ink_crop_pixels"],
        frame["border_pixels"],
    )
    if (
        not isinstance(shape, list)
        or len(shape) != 3
        or any(type(v) is not int for v in shape)
        or not 1 <= shape[0] <= 256
        or not 1 <= shape[1] <= 4096
        or shape[2] != 3
        or shape[0] * shape[1] > MAX_PIXELS
        or not isinstance(crop, list)
        or len(crop) != 4
        or any(type(v) is not int for v in crop)
        or type(border) is not int
        or not 0 < border <= 32
        or not border == crop[0] == crop[1] == shape[1] - crop[2] == shape[0] - crop[3]
        or not crop[0] < crop[2]
        or not crop[1] < crop[3]
        or not isinstance(frame["source_pixel_sha256"], str)
        or not re.fullmatch(r"[a-f0-9]{64}", frame["source_pixel_sha256"])
    ):
        raise ValueError("Unproved complete original row padding")
    compact = row_recognition_border(crop[3] - crop[1], border)
    return compact if compact != border else None


def preparation_shapes(frame, *, version):
    """The exact request sequence; historical evidence retains its old recipe."""
    compact = checked_frame(frame)
    shape, crop, border = (
        frame["source_shape"],
        frame["ink_crop_pixels"],
        frame["border_pixels"],
    )
    shapes = [tuple(shape)]
    if compact is not None:
        shapes.append(
            (crop[3] - crop[1] + 2 * compact, crop[2] - crop[0] + 2 * compact, 3)
        )
    if version >= 5:
        horizontal = max(border, crop[3] - crop[1])
        width = crop[2] - crop[0] + 2 * horizontal
        candidate = (shape[0], width, 3)
        if candidate not in shapes and width <= 4096 and shape[0] * width <= MAX_PIXELS:
            shapes.append(candidate)
    return tuple(shapes)


def preparation_views(image, *, version):
    frame, compact = row_frame(image)
    shapes = preparation_shapes(frame, version=version)
    views = [image]
    if compact is not None:
        views.append(compact)
    if len(shapes) > len(views):
        x0, y0, x1, y1 = frame["ink_crop_pixels"]
        border = frame["border_pixels"]
        horizontal = max(border, y1 - y0)
        views.append(
            cv2.copyMakeBorder(
                image[y0:y1, x0:x1],
                border,
                border,
                horizontal,
                horizontal,
                cv2.BORDER_CONSTANT,
                value=(255, 255, 255),
            )
        )
    if tuple(tuple(view.shape) for view in views) != shapes:
        raise ValueError("Original blank-padding preparation differs")
    for view in views:
        frame_digest(view)
    return frame, tuple(views)
