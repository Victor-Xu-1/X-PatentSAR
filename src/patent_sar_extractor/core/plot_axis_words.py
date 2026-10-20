"""Original quantitative-axis word observation and exact saved-source replay."""

import hashlib

import numpy as np

from .cell_ocr_observation import observe_cell
from .cell_ocr_scores import confidence_value
from .cell_raster import retained_pixel_origin
from .cell_text_proof import valid_text_components
from .cell_word_orientation import rectified_word, valid_word_frame, word_frame
from .page_ocr_cache import get_ocr_engine
from .plot_reference_geometry import literal
from .plot_reference_pixels import observe_pixels, retained_pixels
from .source_geometry import overlaps

MAX_ROW_PIXELS = 8_000_000
_READING_FIELDS = {
    "method",
    "text",
    "raw_text",
    "confidence",
    "parts",
    "bbox",
    "coordinate_space",
    "ink_crop_pixels",
    "border_pixels",
    "render_dpi",
    "detection_parts",
}


def _same_box(value, expected, *, pixels=False):
    return (
        isinstance(value, list)
        and len(value) == 4
        and all(type(v) is int if pixels else type(v) in (int, float) for v in value)
        and value == expected
    )


def observe_axis_words(page, bounds, *, layout="columns"):
    pixels = observe_pixels(page, bounds, MAX_ROW_PIXELS)
    packet = {"bbox": bounds, "pixels": pixels, "readings": []}
    if pixels is None:
        return packet
    engine = get_ocr_engine()
    if not engine or engine[0] != "rapidocr":
        return packet
    for original, dpi in zip(pixels["readings"], (400, 600)):
        mask = retained_pixels(original, bounds, dpi, MAX_ROW_PIXELS)
        frame = word_frame(mask, dpi, layout=layout)
        reading = {"dpi": dpi, "frame": frame, "words": []}
        packet["readings"].append(reading)
        if frame is None:
            continue
        for box in frame["word_bounds"]:
            view = rectified_word(mask, box, frame["angle"], dpi)
            observed = observe_cell(
                view, "header", dpi, engine[1], lambda text, _: text
            )
            evidence = observed.evidence(dpi, [0, 0, view.shape[1], view.shape[0]])
            evidence["coordinate_space"] = "oriented_axis_word_pixels"
            reading["words"].append(
                {
                    "bbox": box,
                    "view_sha256": hashlib.sha256(view.tobytes()).hexdigest(),
                    "reading": evidence,
                }
            )
    return packet


def _word_reading(word, mask, box, angle, dpi):
    if not isinstance(word, dict) or set(word) != {"bbox", "view_sha256", "reading"}:
        return None
    if not _same_box(word["bbox"], box, pixels=True):
        return None
    view = rectified_word(mask, box, angle, dpi)
    reading = word["reading"]
    rows, columns = np.nonzero(np.min(view, axis=2) < 180)
    crop = [
        int(columns.min()),
        int(rows.min()),
        int(columns.max()) + 1,
        int(rows.max()) + 1,
    ]
    if (
        word["view_sha256"] != hashlib.sha256(view.tobytes()).hexdigest()
        or not isinstance(reading, dict)
        or set(reading) - {"single_row_readings"} != _READING_FIELDS
        or not _same_box(
            reading["bbox"], [0, 0, view.shape[1], view.shape[0]], pixels=True
        )
        or reading["coordinate_space"] != "oriented_axis_word_pixels"
        or not _same_box(reading["ink_crop_pixels"], crop, pixels=True)
        or type(reading["border_pixels"]) is not int
        or reading["border_pixels"] != max(3, round(dpi / 72 * 1.5))
        or not isinstance(reading["parts"], list)
        or len(reading["parts"]) != 1
        or reading["detection_parts"] != []
        or not valid_text_components(reading, dpi)
        or not 0 < len(reading["text"].strip()) <= 64
    ):
        return None
    return reading["text"]


def _point_box(box, bounds, dpi, reading):
    origin = retained_pixel_origin(reading, bounds, dpi)
    return [v * 72 / dpi + origin[i % 2] for i, v in enumerate(box)]


def axis_word_parts(packet, bounds, *, layout="columns", with_scope=False):
    """Literal words only after full mask/order/transform/confidence replay."""
    if (
        not isinstance(packet, dict)
        or set(packet) != {"bbox", "pixels", "readings"}
        or not _same_box(packet["bbox"], bounds)
        or not isinstance(packet["pixels"], dict)
        or set(packet["pixels"]) != {"bbox", "readings"}
        or not _same_box(packet["pixels"]["bbox"], bounds)
        or not isinstance(packet["pixels"]["readings"], list)
        or len(packet["pixels"]["readings"]) != 2
        or not isinstance(packet["readings"], list)
        or len(packet["readings"]) != 2
    ):
        return None
    observations = []
    for pixels, reading, dpi in zip(
        packet["pixels"]["readings"], packet["readings"], (400, 600)
    ):
        mask = retained_pixels(pixels, bounds, dpi, MAX_ROW_PIXELS)
        if (
            mask is None
            or not isinstance(reading, dict)
            or set(reading) != {"dpi", "frame", "words"}
            or type(reading["dpi"]) is not int
            or reading["dpi"] != dpi
            or not valid_word_frame(reading["frame"], mask, dpi, layout=layout)
            or not isinstance(reading["words"], list)
            or len(reading["words"]) != len(reading["frame"]["word_bounds"])
        ):
            return None
        parts = []
        for word, box in zip(reading["words"], reading["frame"]["word_bounds"]):
            text = _word_reading(word, mask, box, reading["frame"]["angle"], dpi)
            if text is None:
                return None
            parts.append({"text": text, "bbox": _point_box(box, bounds, dpi, pixels)})
        observations.append(parts)
    if len(observations[0]) != len(observations[1]):
        return None
    result = []
    for first, second in zip(*observations):
        if literal(first["text"]) != literal(second["text"]) or any(
            abs(a - b) > 1.2 for a, b in zip(first["bbox"], second["bbox"])
        ):
            return None
        result.append(
            {
                "text": first["text"],
                "bbox": [
                    min(first["bbox"][0], second["bbox"][0]),
                    min(first["bbox"][1], second["bbox"][1]),
                    max(first["bbox"][2], second["bbox"][2]),
                    max(first["bbox"][3], second["bbox"][3]),
                ],
            }
        )
    scope = bounds
    if layout == "rows":
        lanes = [
            _point_box(reading["frame"]["lane_bounds"], bounds, dpi, original)
            for reading, original, dpi in zip(
                packet["readings"],
                packet["pixels"]["readings"],
                (400, 600),
                strict=True,
            )
        ]
        scope = [
            min(box[0] for box in lanes),
            bounds[1],
            max(box[2] for box in lanes),
            bounds[3],
        ]
    return (result, scope) if with_scope else result


def refined_axis_tokens(tokens, independent_tokens, parts, bounds):
    """A transient proved projection; original raw packets remain unchanged.

    Every qualified original literal in the row is a veto if it conflicts with
    the independent reading. Weak observations remain retained, not rewritten.
    """
    for token in [*tokens, *independent_tokens]:
        if not token["text"].strip() or not overlaps(token["bbox"], bounds):
            continue
        score = confidence_value(token.get("confidence"))
        qualified = (
            token.get("confidence_valid", True) is True
            and score is not None
            and score >= 0.85
        )
        if qualified and not any(
            literal(token["text"]) == literal(part["text"])
            and overlaps(token["bbox"], part["bbox"])
            for part in parts
        ):
            return None
    return [p for p in tokens if not overlaps(p["bbox"], bounds)] + parts
