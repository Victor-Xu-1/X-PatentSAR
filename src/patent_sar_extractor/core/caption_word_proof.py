"""Pure retained role/ID word proof; a page nomination cannot choose its form."""

import math
import re
from collections.abc import Mapping

import numpy as np

from patent_sar_extractor.contracts import CAPTION_WORD_FORM_VERSION

from .caption_word_geometry import MAX_CAPTION_WORD_PIXELS, caption_word_partitions
from .cell_frame_proof import valid_cell_frame
from .cell_ocr_scores import confidence_value
from .cell_raster import retained_pixel_origin
from .compound_caption import prefixed_label
from .printed_identifiers import LABEL_KIND, identifier_key, identifier_text
from .source_observations import source_observation_status
from .source_section_roles import nonfinal_original_label

WORD_FORM_METHOD = "caption_word_form"


def merged_caption_nominee(label, observation, bounds):
    if observation.get("method") != "page_ocr_cell":
        return None
    raw = identifier_text(observation.get("text", "")).upper().removesuffix(".")
    source = observation.get("source_observation")
    if (
        not label
        or not raw.endswith(label)
        or not raw[: -len(label)].isalpha()
        or prefixed_label(raw)
        or nonfinal_original_label(raw)
        or not isinstance(source, dict)
        or observation.get("bbox") != list(bounds)
        or source_observation_status(source, bounds, observation.get("text"))
        != "qualified"
        or source.get("origin") != "raster"
        or len(source["tokens"]) != 1
    ):
        return None
    return source["tokens"][0]["bbox"]


def _selected_partition(partitions, expected, role, label):
    if not isinstance(partitions, list) or len(partitions) != len(expected):
        return None
    selected = []
    for partition, bounds in zip(partitions, expected, strict=True):
        if not isinstance(partition, dict) or set(partition) != {"words"}:
            return None
        words = partition["words"]
        if not isinstance(words, list) or len(words) != 2:
            return None
        qualified = True
        for word, box in zip(words, bounds, strict=True):
            if (
                not isinstance(word, dict)
                or set(word) != {"bbox", "text", "confidence", "pixel_sha256"}
                or word["bbox"] != box
                or not isinstance(word["text"], str)
                or not 0 < len(word["text"]) <= 128
                or confidence_value(word["confidence"]) is None
                or not isinstance(word["pixel_sha256"], str)
                or re.fullmatch(r"[a-f0-9]{64}", word["pixel_sha256"]) is None
            ):
                return None
            score = confidence_value(word["confidence"])
            qualified &= score is not None and score >= 0.85
        if (
            qualified
            and words[0]["text"].casefold() == role.casefold()
            and identifier_key(words[1]["text"], terminal_period=True) == label
        ):
            selected.append(bounds)
    return selected[0] if len(selected) == 1 else None


def whole_caption_reads(label, observations):
    readings = [
        o
        for o in observations
        if o.get("method") in {"cell_ocr_400dpi", "cell_ocr_600dpi"}
    ]
    if len(readings) != 2 or [r.get("method") for r in readings] != [
        "cell_ocr_400dpi",
        "cell_ocr_600dpi",
    ]:
        return None
    for reading in readings:
        score = confidence_value(reading.get("confidence"))
        if (
            score is None
            or score < 0.85
            or reading.get("text") != label
            or prefixed_label(reading.get("raw_text", "")) != label
        ):
            return None
    return readings


def word_form_readings(label, packet, observations):
    """Return bounded original masks only if all whole/word observations agree."""
    from .plot_reference_pixels import retained_pixels

    whole = whole_caption_reads(label, observations)
    if (
        whole is None
        or not isinstance(packet, dict)
        or set(packet) != {"version", "status", "bbox", "readings"}
        or type(packet["version"]) is not int
        or packet["version"] != CAPTION_WORD_FORM_VERSION
        or packet["status"] != "observed"
        or not isinstance(packet["bbox"], list)
        or len(packet["bbox"]) != 4
        or any(
            type(v) not in {int, float}
            or not math.isfinite(v)
            or not 0 <= v <= 1_000_000
            for v in packet["bbox"]
        )
        or not packet["bbox"][0] < packet["bbox"][2]
        or not packet["bbox"][1] < packet["bbox"][3]
        or not isinstance(packet["readings"], list)
        or len(packet["readings"]) != 2
    ):
        return None
    result = []
    for item, reading, dpi in zip(packet["readings"], whole, (400, 600), strict=True):
        if not isinstance(item, dict) or set(item) != {"pixels", "partitions"}:
            return None
        pixels, partitions = item["pixels"], item["partitions"]
        mask = retained_pixels(pixels, packet["bbox"], dpi, MAX_CAPTION_WORD_PIXELS)
        if mask is None:
            return None
        expected = caption_word_partitions(mask, dpi)
        frame = {
            "dpi": dpi,
            "shape": pixels["shape"],
            "pixel_sha256": pixels["pixel_sha256"],
        }
        if (
            expected is None
            or reading.get("bbox") != packet["bbox"]
            or reading.get("source_frame") != frame
            or pixels.get("source_window") != reading.get("source_window")
            or not valid_cell_frame(frame, reading, packet["bbox"], dpi)
        ):
            return None
        yy, xx = np.where(mask)
        if reading["ink_crop_pixels"] != [
            int(xx.min()),
            int(yy.min()),
            int(xx.max()) + 1,
            int(yy.max()) + 1,
        ]:
            return None
        role = re.match(LABEL_KIND, identifier_text(reading["raw_text"]), re.IGNORECASE)
        if role is None:
            return None
        selected = _selected_partition(partitions, expected, role.group(), label)
        if selected is None:
            return None
        result.append((mask, selected))
    origins = [
        retained_pixel_origin(item["pixels"], packet["bbox"], dpi)
        for item, dpi in zip(packet["readings"], (400, 600), strict=True)
    ]
    for first, second in zip(result[0][1], result[1][1], strict=True):
        if any(
            abs(
                origins[0][axis % 2]
                + first[axis] * 72 / 400
                - origins[1][axis % 2]
                - second[axis] * 72 / 600
            )
            > 1
            for axis in range(4)
        ):
            return None
    return result


def caption_form_aliases(label, observations):
    """None means invalid proof; an empty set means the unchanged strict policy."""
    if not isinstance(observations, (list, tuple)) or any(
        not isinstance(o, Mapping) for o in observations
    ):
        return None
    witnesses = [
        o
        for o in observations
        if o.get("method") == WORD_FORM_METHOD or "caption_word_form" in o
    ]
    if not witnesses:
        return set()
    if (
        len(witnesses) != 1
        or set(witnesses[0]) != {"method", "caption_word_form"}
        or witnesses[0]["method"] != WORD_FORM_METHOD
    ):
        return None
    packet = witnesses[0]["caption_word_form"]
    frames = word_form_readings(label, packet, observations)
    if frames is None:
        return None
    aliases = set()
    for index, observation in enumerate(observations):
        box = merged_caption_nominee(label, observation, packet["bbox"])
        if box is None:
            continue
        # The page token must actually span BOTH independent original words,
        # not an isolated known series/suffix or a different neighbouring cell.
        for (_mask, words), item, dpi in zip(
            frames, packet["readings"], (400, 600), strict=True
        ):
            scale = dpi / 72
            origin = retained_pixel_origin(item["pixels"], packet["bbox"], dpi)
            if any(
                not (
                    box[0] <= origin[0] + (w[0] + w[2]) / 2 / scale <= box[2]
                    and box[1] <= origin[1] + (w[1] + w[3]) / 2 / scale <= box[3]
                )
                for w in words
            ):
                break
        else:
            aliases.add(index)
    return aliases if aliases else None
