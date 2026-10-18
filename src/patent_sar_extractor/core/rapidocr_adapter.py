"""Lossless source-canvas bounds for the single optional RapidOCR backend."""

from __future__ import annotations

import numpy as np

MAX_PADDED_PIXELS = 8_000_000


def _reduced_shape(h: int, w: int, limit: int) -> tuple[int, int]:
    """Mirror the pinned SDK's floor then nearest-32 resize, including ties."""
    ratio = limit / max(h, w)
    reduced_h = int(round(int(h * ratio) / 32) * 32)
    reduced_w = int(round(int(w * ratio) / 32) * 32)
    return reduced_h, reduced_w


def source_canvas(image: np.ndarray, max_side_len: int) -> np.ndarray:
    """Keep valid inputs identical; pad only a canvas the SDK cannot resize.

    The SDK rounds an already floored dimension to a multiple of 32; 16 rounds
    to 0. Trailing white pixels keep every original pixel and its top-left origin.
    The SDK still owns all resizing, inference, confidence and inverse geometry.
    No source row is discarded and no extra OCR view/model/retry is introduced.
    """
    if (
        not isinstance(image, np.ndarray)
        or image.dtype != np.uint8
        or image.ndim != 3
        or image.shape[2] != 3
        or min(image.shape[:2]) <= 0
        or type(max_side_len) is not int
        or max_side_len < 32
    ):
        raise ValueError("Invalid source OCR image or resize limit")
    h, w = image.shape[:2]
    longest = max(h, w)
    if longest <= max_side_len or min(_reduced_shape(h, w, max_side_len)) > 0:
        return image

    # 17 survives nearest-32 quantization. One further source pixel protects the
    # SDK's floating-point floor at exact integer boundaries; no ink is altered.
    minimum = (17 * longest + max_side_len - 1) // max_side_len + 1
    padded_h, padded_w = max(h, minimum), max(w, minimum)
    if (
        padded_h * padded_w > MAX_PADDED_PIXELS
        or min(_reduced_shape(padded_h, padded_w, max_side_len)) <= 0
    ):
        raise ValueError(
            f"Source OCR canvas exceeds bounded padding: {h}x{w} -> "
            f"{padded_h}x{padded_w}; limit={MAX_PADDED_PIXELS} pixels"
        )
    padded = np.full((padded_h, padded_w, 3), 255, dtype=np.uint8)
    padded[:h, :w] = image
    return padded


def create_rapidocr(**options):
    """Build the existing SDK lazily, so its optional-runtime policy is unchanged."""
    from rapidocr_onnxruntime import RapidOCR

    class SourceRapidOCR(RapidOCR):
        def preprocess(self, image):
            # __call__ records the original dimensions before this hook; SDK box
            # mapping therefore retains the original frame and clips its bounds.
            return super().preprocess(source_canvas(image, self.max_side_len))

    return SourceRapidOCR(**options)
