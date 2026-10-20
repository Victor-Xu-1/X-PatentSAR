"""Bounded retained plot pixels, sharing the original cell rendering authority."""

import hashlib
import re
import zlib

import numpy as np

from .cell_raster import original_reading_image, render_cell_raster, valid_source_window
from .cell_rendering import CellRenderLimit


def pixel_reading(image, dpi, *, source_window=None):
    """One exact RGB digest and bounded binary-ink encoding for source readers."""
    return {
        "dpi": dpi,
        "shape": list(image.shape),
        "pixel_sha256": hashlib.sha256(image.tobytes()).hexdigest(),
        "mask_encoding": "zlib-packbits-v1",
        "mask_hex": zlib.compress(
            np.packbits(np.min(image, axis=2) < 180).tobytes()
        ).hex(),
        **({"source_window": source_window} if source_window is not None else {}),
    }


def observe_pixels(page, bounds, maximum_pixels, *, resolutions=(400, 600)):
    if (
        not isinstance(resolutions, tuple)
        or any(type(dpi) is not int for dpi in resolutions)
        or resolutions not in ((400,), (400, 600))
    ):
        raise ValueError("Unsupported original-pixel observation resolutions")
    readings = []
    for dpi in resolutions:
        try:
            raster = render_cell_raster(
                page, bounds, dpi, maximum_pixels=maximum_pixels
            )
        except CellRenderLimit:
            return None
        image = raster.image
        if image.shape[0] * image.shape[1] > maximum_pixels:
            return None
        readings.append(pixel_reading(image, dpi, source_window=raster.source_window))
    return {"bbox": bounds, "readings": readings}


def retained_pixels(reading, bounds, dpi, maximum_pixels):
    if not isinstance(reading, dict) or set(reading) - {"source_window"} != {
        "dpi",
        "shape",
        "pixel_sha256",
        "mask_encoding",
        "mask_hex",
    }:
        return None
    shape = reading["shape"]
    if (
        type(reading["dpi"]) is not int
        or reading["dpi"] != dpi
        or not isinstance(shape, list)
        or len(shape) != 3
        or any(type(v) is not int or v <= 0 for v in shape)
        or shape[2] != 3
        or shape[0] * shape[1] > maximum_pixels
        or not isinstance(reading["pixel_sha256"], str)
        or not re.fullmatch(r"[a-f0-9]{64}", reading["pixel_sha256"])
        or not isinstance(reading["mask_hex"], str)
        or reading["mask_encoding"] != "zlib-packbits-v1"
        or len(reading["mask_hex"]) > 2 * (((shape[0] * shape[1] + 7) // 8) + 512)
        or not re.fullmatch(r"[a-f0-9]+", reading["mask_hex"])
    ):
        return None
    if "source_window" in reading:
        if (
            not valid_source_window(reading["source_window"], bounds, dpi, shape)
            or reading["source_window"]["source_shape"][0]
            * reading["source_window"]["source_shape"][1]
            > maximum_pixels
        ):
            return None
    elif (
        abs(shape[1] - (bounds[2] - bounds[0] - 3) * dpi / 72) > 2
        or abs(shape[0] - (bounds[3] - bounds[1] - 2.4) * dpi / 72) > 2
    ):
        return None
    count = shape[0] * shape[1]
    byte_count = (count + 7) // 8
    try:
        decoder = zlib.decompressobj()
        raw = decoder.decompress(bytes.fromhex(reading["mask_hex"]), byte_count + 1)
    except (ValueError, zlib.error):
        return None
    if (
        len(raw) != byte_count
        or not decoder.eof
        or decoder.unconsumed_tail
        or decoder.unused_data
    ):
        return None
    bits = np.unpackbits(np.frombuffer(raw, dtype=np.uint8))
    return bits[:count].reshape(shape[:2]) if not np.any(bits[count:]) else None


def replay_pixels(page, bounds, reading, *, maximum_pixels=8_000_000):
    """Exact readback of retained full-source or historical pixels, no OCR."""
    dpi = reading["dpi"]
    if retained_pixels(reading, bounds, dpi, maximum_pixels) is None:
        raise ValueError("Invalid retained original pixel reading")
    primary = {
        "source_frame": {key: reading[key] for key in ("dpi", "shape", "pixel_sha256")},
        **(
            {"source_window": reading["source_window"]}
            if "source_window" in reading
            else {}
        ),
    }
    image = original_reading_image(page, bounds, dpi, primary)
    observed = pixel_reading(image, dpi, source_window=reading.get("source_window"))
    if observed != reading:
        raise ValueError("Retained original pixels differ from the actual source")
    return image
