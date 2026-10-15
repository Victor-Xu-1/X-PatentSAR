"""Validate one original image response without dropping tokens or coordinates."""

import math

from .page_ocr_execution import PageObservationError


def paddlex_page(payload: object) -> tuple[list[str], list[list[float]]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("result"), dict):
        raise PageObservationError(
            "PaddleX page response is missing its result envelope"
        )
    results = payload["result"].get("ocrResults")
    if not isinstance(results, list) or len(results) > 1:
        raise PageObservationError(
            "PaddleX page response has ambiguous image ownership"
        )
    if not results:
        return [], []
    result = results[0].get("prunedResult") if isinstance(results[0], dict) else None
    if not isinstance(result, dict):
        raise PageObservationError(
            "PaddleX page response is missing original observations"
        )
    texts, boxes = result.get("rec_texts"), result.get("rec_boxes")
    if (
        not isinstance(texts, list)
        or not isinstance(boxes, list)
        or len(texts) != len(boxes)
    ):
        raise PageObservationError("PaddleX page text and coordinates are incomplete")
    pairs = []
    for text, box in zip(texts, boxes, strict=True):
        if (
            not isinstance(text, str)
            or not isinstance(box, list)
            or len(box) != 4
            or any(
                type(value) not in {int, float} or not math.isfinite(value)
                for value in box
            )
        ):
            raise PageObservationError(
                "PaddleX page observation has invalid text or coordinates"
            )
        if box[2] < box[0] or box[3] < box[1]:
            raise PageObservationError(
                "PaddleX page observation has inverted coordinates"
            )
        if text.strip():
            pairs.append((text.strip(), box))
    return [text for text, _ in pairs], [box for _, box in pairs]
