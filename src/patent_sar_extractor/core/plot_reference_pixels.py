"""Bounded retained plot pixels, sharing the original cell rendering authority."""

import hashlib
import re
import zlib

import numpy as np

from .table_cells import CellRenderLimit, cell_image


def observe_pixels(page, bounds, maximum_pixels):
    readings = []
    for dpi in (400, 600):
        try:
            image = cell_image(page, bounds, dpi, maximum_pixels=maximum_pixels)
        except CellRenderLimit:
            return None
        if image.shape[0] * image.shape[1] > maximum_pixels:
            return None
        readings.append(
            {
                "dpi": dpi,
                "shape": list(image.shape),
                "pixel_sha256": hashlib.sha256(image.tobytes()).hexdigest(),
                "mask_encoding": "zlib-packbits-v1",
                "mask_hex": zlib.compress(
                    np.packbits(np.min(image, axis=2) < 180).tobytes()
                ).hex(),
            }
        )
    return {"bbox": bounds, "readings": readings}


def retained_pixels(reading, bounds, dpi, maximum_pixels):
    if not isinstance(reading, dict) or set(reading) != {
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
        or abs(shape[1] - (bounds[2] - bounds[0] - 3) * dpi / 72) > 2
        or abs(shape[0] - (bounds[3] - bounds[1] - 2.4) * dpi / 72) > 2
        or not isinstance(reading["pixel_sha256"], str)
        or not re.fullmatch(r"[a-f0-9]{64}", reading["pixel_sha256"])
        or not isinstance(reading["mask_hex"], str)
        or reading["mask_encoding"] != "zlib-packbits-v1"
        or len(reading["mask_hex"]) > 2 * (((shape[0] * shape[1] + 7) // 8) + 512)
        or not re.fullmatch(r"[a-f0-9]+", reading["mask_hex"])
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
