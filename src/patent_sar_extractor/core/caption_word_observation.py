"""Bounded same-engine source-word reads, invoked only for a caption-form conflict."""

import hashlib

import cv2
import numpy as np

from patent_sar_extractor.contracts import CAPTION_WORD_FORM_VERSION

from .caption_word_geometry import MAX_CAPTION_WORD_PIXELS, caption_word_partitions
from .caption_word_proof import WORD_FORM_METHOD
from .cell_ocr_scores import confidence_value
from .page_ocr_cache import get_ocr_engine


def _word_read(engine, image, box, dpi):
    x0, y0, x1, y1 = box
    original = image[y0:y1, x0:x1]
    border = max(3, round(dpi / 72 * 1.5))
    view = cv2.copyMakeBorder(
        original,
        border,
        border,
        border,
        border,
        cv2.BORDER_CONSTANT,
        value=(255, 255, 255),
    )
    response, _ = engine(view, use_det=False, use_cls=False)
    if not isinstance(response, (list, tuple)) or len(response) != 1:
        return None
    pair = response[0]
    if (
        not isinstance(pair, (list, tuple))
        or len(pair) != 2
        or not isinstance(pair[0], str)
        or not 0 < len(pair[0]) <= 128
    ):
        return None
    score = confidence_value(pair[1])
    return {
        "bbox": box,
        "text": pair[0],
        "confidence": score,
        "pixel_sha256": hashlib.sha256(original.tobytes()).hexdigest(),
    }


def observe_caption_word_form(page, bounds):
    from .plot_reference_pixels import pixel_reading
    from .table_cells import CellRenderLimit, cell_image

    backend = get_ocr_engine()
    if not backend or backend[0] != "rapidocr":
        return None
    readings = []
    packet = {
        "version": CAPTION_WORD_FORM_VERSION,
        "status": "unresolved",
        "bbox": list(bounds),
        "readings": readings,
    }
    evidence = {"method": WORD_FORM_METHOD, "caption_word_form": packet}
    for dpi in (400, 600):
        try:
            image = cell_image(
                page, bounds, dpi, maximum_pixels=MAX_CAPTION_WORD_PIXELS
            )
        except CellRenderLimit:
            return None
        partitions = caption_word_partitions(np.min(image, axis=2) < 180, dpi)
        if partitions is None:
            readings.append({"pixels": pixel_reading(image, dpi), "partitions": []})
            packet["reason"] = "unresolved_original_word_partitions"
            return evidence
        observed = [
            {"words": [_word_read(backend[1], image, box, dpi) for box in boxes]}
            for boxes in partitions
        ]
        readings.append({"pixels": pixel_reading(image, dpi), "partitions": observed})
        if any(word is None for partition in observed for word in partition["words"]):
            packet["reason"] = "malformed_original_word_read"
            return evidence
        if any(
            word["confidence"] is None
            for partition in observed
            for word in partition["words"]
        ):
            packet["reason"] = "invalid_original_word_confidence"
            return evidence
    packet["status"] = "observed"
    return evidence


def replay_caption_word_form(page, packet):
    """Reopen original pixels only: no OCR, inferred text or saved success flag."""
    from .plot_reference_pixels import pixel_reading
    from .table_cells import cell_image

    frames = {}
    for item, dpi in zip(packet["readings"], (400, 600), strict=True):
        image = cell_image(
            page, packet["bbox"], dpi, maximum_pixels=MAX_CAPTION_WORD_PIXELS
        )
        if pixel_reading(image, dpi) != item["pixels"]:
            raise ValueError("Original caption word pixels differ")
        frames[dpi] = {
            key: item["pixels"][key] for key in ("dpi", "shape", "pixel_sha256")
        }
        boxes = caption_word_partitions(np.min(image, axis=2) < 180, dpi)
        if boxes != [
            [word["bbox"] for word in partition["words"]]
            for partition in item["partitions"]
        ]:
            raise ValueError("Original caption word partition differs")
        for partition in item["partitions"]:
            for word in partition["words"]:
                x0, y0, x1, y1 = word["bbox"]
                if (
                    hashlib.sha256(image[y0:y1, x0:x1].tobytes()).hexdigest()
                    != word["pixel_sha256"]
                ):
                    raise ValueError("Original caption word crop differs")
    return frames
