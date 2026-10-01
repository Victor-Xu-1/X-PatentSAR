"""Bounded atomic image normalization; it never reconstructs chemistry."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import cv2
import numpy as np
from PIL import Image


def preprocess_structure_image(
    image_path: str, output_dir: str, padding: int = 20, long_edge: int = 1024
) -> str:
    """Normalize the same crop with explicit limits and diagnostic failures."""
    if type(padding) is not int or not 0 <= padding <= 128:
        raise ValueError("Image padding must be an integer from 0 to 128")
    if type(long_edge) is not int or not 128 <= long_edge <= 2048:
        raise ValueError("Image long edge must be an integer from 128 to 2048")
    with Image.open(image_path) as source:
        if min(source.size) < 1 or source.width * source.height > 8_000_000:
            raise ValueError(
                "Structure image dimensions exceed the normalization limit"
            )
        rgba = source.convert("RGBA")
        white = Image.new("RGBA", rgba.size, "white")
        white.alpha_composite(rgba)
        gray = cv2.cvtColor(np.asarray(white.convert("RGB")), cv2.COLOR_RGB2GRAY)
    if float(gray.mean()) < 128:
        gray = cv2.bitwise_not(gray)
    if padding:
        gray = cv2.copyMakeBorder(
            gray, padding, padding, padding, padding, cv2.BORDER_CONSTANT, value=255
        )
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    height, width = binary.shape
    scale = long_edge / max(height, width)
    binary = cv2.resize(
        binary,
        (max(1, round(width * scale)), max(1, round(height * scale))),
        interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC,
    )
    encoded, pixels = cv2.imencode(".png", binary)
    if not encoded:
        raise ValueError("Normalized structure image encoding failed")
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / f"{Path(image_path).stem}_preprocessed.png"
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=directory, prefix=".normalize-", suffix=".png", delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(pixels.tobytes())
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return str(target)
