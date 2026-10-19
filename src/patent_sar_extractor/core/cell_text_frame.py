"""One model-free replay for whole-cell and chunk-child physical text rows."""

import cv2

from .cell_header_lines import physical_line_frame

SOURCE_FRAME_FIELDS = ("image_shape", "pixel_sha256", "row_bounds", "ink_pixels")


def original_text_row_frame(image, reading, dpi, *, maximum_rows, maximum_row_height):
    crop, border = reading["ink_crop_pixels"], reading["border_pixels"]
    if crop is None:
        return reading.get("physical_header_lines") is None
    padded = cv2.copyMakeBorder(
        image[crop[1] : crop[3], crop[0] : crop[2]],
        border,
        border,
        border,
        border,
        cv2.BORDER_CONSTANT,
        value=(255, 255, 255),
    )
    actual = physical_line_frame(
        padded,
        border,
        dpi,
        maximum_rows=maximum_rows,
        maximum_row_height=maximum_row_height,
    )
    frame = reading.get("physical_header_lines")
    if frame is None:
        return actual is None
    return (
        isinstance(frame, dict)
        and set(frame) == {"version", "status", *SOURCE_FRAME_FIELDS, "row_readings"}
        and type(frame["version"]) is int
        and frame["version"] == 2
        and isinstance(frame["status"], str)
        and frame["status"] in {"observed", "unresolved"}
        and isinstance(frame["row_readings"], list)
        and isinstance(frame["row_bounds"], list)
        and len(frame["row_readings"]) == len(frame["row_bounds"])
        and actual is not None
        and all(frame[k] == actual[k] for k in SOURCE_FRAME_FIELDS)
    )
