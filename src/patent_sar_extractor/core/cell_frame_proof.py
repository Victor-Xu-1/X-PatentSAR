"""Pure shared pixel/crop frame validation for bounded original cell readers."""

import hashlib
import math
import re


def inside_box(box, outer):
    return (
        isinstance(box, list)
        and len(box) == 4
        and all(type(v) in {int, float} and math.isfinite(v) for v in box)
        and outer[0] <= box[0] < box[2] <= outer[2]
        and outer[1] <= box[1] < box[3] <= outer[3]
    )


def valid_cell_frame(frame, reading, bounds, dpi):
    if (
        not isinstance(frame, dict)
        or not isinstance(reading, dict)
        or set(frame) != {"dpi", "shape", "pixel_sha256"}
        or type(frame["dpi"]) is not int
        or frame["dpi"] != dpi
        or not isinstance(frame["shape"], list)
        or len(frame["shape"]) != 3
        or any(type(v) is not int or v <= 0 for v in frame["shape"])
        or frame["shape"][2] != 3
        or frame["shape"][0] * frame["shape"][1] > 8_000_000
        or abs(frame["shape"][1] - (bounds[2] - bounds[0] - 3) * dpi / 72) > 2
        or abs(frame["shape"][0] - (bounds[3] - bounds[1] - 2.4) * dpi / 72) > 2
        or not isinstance(frame["pixel_sha256"], str)
        or not re.fullmatch(r"[a-f0-9]{64}", frame["pixel_sha256"])
    ):
        return False
    crop, border = reading.get("ink_crop_pixels"), reading.get("border_pixels")
    chunks = reading.get("physical_text_chunks")
    if chunks is not None:
        return (
            isinstance(chunks, dict)
            and chunks.get("image_shape") == frame["shape"]
            and chunks.get("pixel_sha256") == frame["pixel_sha256"]
            and crop is None
            and type(border) is int
            and border == 0
            and reading.get("parts") == []
            and reading.get("detection_parts") == []
        )
    return valid_ink_extent(reading, frame["shape"])


def valid_ink_extent(reading, shape):
    """Pixel-crop ownership, not a claim that the captured text is qualified."""
    crop, border = reading.get("ink_crop_pixels"), reading.get("border_pixels")
    if crop is None:
        return (
            reading.get("parts") == []
            and reading.get("detection_parts") == []
            and reading.get("raw_text") == reading.get("text") == ""
            and type(border) is int
            and border == 0
        )
    if (
        type(border) is not int
        or not 0 < border <= 32
        or not inside_box(crop, [0, 0, shape[1], shape[0]])
        or any(type(v) is not int for v in crop)
    ):
        return False
    pixels = [0, 0, crop[2] - crop[0] + 2 * border, crop[3] - crop[1] + 2 * border]
    for name in ("parts", "detection_parts"):
        parts = reading.get(name)
        if not isinstance(parts, list) or len(parts) > 32:
            return False
        for part in parts:
            if (
                not isinstance(part, dict)
                or part.get("coordinate_space") != "cell_ink_crop_pixels"
            ):
                return False
            points = part.get("bbox")
            if points is None:
                if len(parts) != 1:
                    return False
                continue
            if (
                not isinstance(points, list)
                or len(points) != 4
                or any(
                    not isinstance(point, list)
                    or len(point) != 2
                    or any(
                        type(v) not in {int, float} or not math.isfinite(v)
                        for v in point
                    )
                    for point in points
                )
            ):
                return False
            if not inside_box(
                [
                    min(p[0] for p in points),
                    min(p[1] for p in points),
                    max(p[0] for p in points),
                    max(p[1] for p in points),
                ],
                pixels,
            ):
                return False
    return True


def original_cell_frame_matches(
    reading, page, *, maximum_row_height=12, maximum_rows=None
):
    """Replay complete original pixels and ink extent, never text recognition."""
    import cv2
    import numpy as np

    from .cell_text_scope import scoped_height
    from .table_cells import cell_image

    try:
        height = (
            scoped_height(
                reading,
                maximum_row_height=maximum_row_height,
                maximum_rows=maximum_rows,
            )
            if "text_scope" in reading
            else 12
        )
    except (TypeError, ValueError):
        return False

    bounds, dpi, frame = (
        reading.get("bbox"),
        reading.get("render_dpi"),
        reading.get("source_frame"),
    )
    if (
        not inside_box(bounds, [0, 0, page.rect.width, page.rect.height])
        or type(dpi) is not int
        or dpi not in (400, 600)
        or not valid_cell_frame(frame, reading, bounds, dpi)
    ):
        return False
    image = cell_image(page, bounds, dpi)
    if (
        frame["shape"] != list(image.shape)
        or frame["pixel_sha256"] != hashlib.sha256(image.tobytes()).hexdigest()
    ):
        return False
    if "physical_text_chunks" in reading:
        from .cell_text_chunk_pixels import original_text_chunk_pixels

        return original_text_chunk_pixels(
            image, reading, dpi, maximum_row_height=height
        )
    ys, xs = np.where(cv2.cvtColor(image, cv2.COLOR_RGB2GRAY) < 180)
    crop = (
        [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1]
        if len(xs)
        else None
    )
    if reading.get("ink_crop_pixels") != crop:
        return False
    if "text_scope" in reading:
        from .cell_text_frame import original_text_row_frame

        return original_text_row_frame(
            image,
            reading,
            dpi,
            maximum_rows=reading["text_scope"]["maximum_rows"],
            maximum_row_height=height,
        )
    # Historical unmarked ordinary cells keep their original pixel/crop contract.
    return True
