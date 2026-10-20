"""Physical closed-cell proof is deliberately independent of label quality."""

import math
import re

from .caption_source_windows import CAPTION_READ_PADDING
from .cell_frame_proof import inside_box, valid_cell_frame
from .cell_ocr_scores import confidence_value
from .cell_raster import cell_pixel_rect, valid_source_window
from .cell_rule_pixels import MAX_RULE_THICKNESS_PT
from .source_cell_claims import cell_source_status, native_witness


def valid_closed_caption_scope(scope, cell):
    try:
        if not isinstance(scope, dict) or set(scope) != {"version", "bounds", "views"}:
            return False
        bounds, views = scope["bounds"], scope["views"]
        if (
            type(scope["version"]) is not int
            or scope["version"] != 1
            or not inside_box(bounds, [0, 0, 1_000_000, 1_000_000])
            or not inside_box(cell, bounds)
            or bounds == cell
            or any(
                abs(a - b) > CAPTION_READ_PADDING
                for a, b in zip(bounds, cell, strict=True)
            )
            or not isinstance(views, list)
            or len(views) != 2
        ):
            return False
        for dpi, view in zip((400, 600), views, strict=True):
            if not isinstance(view, dict) or set(view) != {
                "frame",
                "window",
                "closed_bands",
            }:
                return False
            frame, window, bands = view["frame"], view["window"], view["closed_bands"]
            if (
                not isinstance(frame, dict)
                or set(frame) != {"dpi", "shape", "pixel_sha256"}
                or type(frame["dpi"]) is not int
                or frame["dpi"] != dpi
                or not isinstance(frame["pixel_sha256"], str)
                or not re.fullmatch(r"[a-f0-9]{64}", frame["pixel_sha256"])
                or not valid_source_window(window, bounds, dpi, frame["shape"])
                or window["purpose"] != "pixels"
                or window["frame_strips"] is not None
                or frame["pixel_sha256"] != window["source_pixel_sha256"]
                or math.prod(frame["shape"][:2]) > 2_000_000
                or not isinstance(bands, list)
                or len(bands) != 4
            ):
                return False
            extent = cell_pixel_rect(bounds, dpi)
            for axis, band, edge in zip(
                (0, 0, 1, 1), bands, (cell[1], cell[3], cell[0], cell[2]), strict=True
            ):
                position = edge * dpi / 72 - (extent.y0 if axis == 0 else extent.x0)
                margin = math.ceil(MAX_RULE_THICKNESS_PT * dpi / 72)
                if (
                    not isinstance(band, list)
                    or not band
                    or any(
                        type(value) is not int
                        or not 0 <= value < frame["shape"][axis]
                        or abs(value - position) > margin + 1
                        for value in band
                    )
                    or band != sorted(set(band))
                    or (band[-1] - band[0] + 1) * 72 / dpi > MAX_RULE_THICKNESS_PT
                ):
                    return False
        return True
    except (KeyError, TypeError, ValueError, OverflowError):
        return False


def physical_caption_readings(observations, bounds):
    """Existing whole-cell originals are required, never a nominal token alone."""
    if not isinstance(observations, list) or not 1 <= len(observations) <= 4:
        return False
    optical, native, profiles = set(), False, False
    for reading in observations:
        if not isinstance(reading, dict) or reading.get("bbox") != bounds:
            return False
        method = reading.get("method")
        if method in {"native_cell", "page_ocr_cell"}:
            status = cell_source_status(reading)
            if status in {"invalid", "legacy"}:
                return False
            profile = reading["source_observation"]
            profiles |= bool(profile["tokens"])
            native |= (
                method == "native_cell"
                and not native_witness(reading)
                and status == "qualified"
            )
        elif method in {"cell_ocr_400dpi", "cell_ocr_600dpi"}:
            dpi = 400 if method == "cell_ocr_400dpi" else 600
            if (
                "source_window" not in reading
                or confidence_value(reading.get("confidence")) is None
                or not valid_cell_frame(
                    reading.get("source_frame"), reading, bounds, dpi
                )
            ):
                return False
            optical.add(dpi)
        else:
            return False
    return profiles and (native or optical == {400, 600})
