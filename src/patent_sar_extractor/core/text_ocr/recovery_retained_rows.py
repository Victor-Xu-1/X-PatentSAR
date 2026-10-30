"""Conserve independently agreeing primary rows without claiming model calls."""

import re

from ..cell_text_proof import original_physical_parts
from .cell_frames import literal
from .cell_packets import primary_structure
from .protocol import frame_digest


def retained_pair_rows(primaries, frames, *, maximum_rows, maximum_row_height):
    """A common physical ordinal is usable only in BOTH qualified primaries."""
    try:
        rows = []
        for primary, frame, dpi in zip(primaries, frames, (400, 600), strict=True):
            if (
                not isinstance(primary, dict)
                or any(
                    not isinstance(primary.get(key), list) or len(primary[key]) > 32
                    for key in ("parts", "detection_parts")
                )
                or not primary_structure(primary, frame, primary["bbox"], dpi)
            ):
                return ((), ())
            parts = original_physical_parts(
                primary,
                maximum_rows=maximum_rows,
                maximum_row_height=maximum_row_height,
            )
            if parts is None:
                return ((), ())
            rows.append(parts)
        if len(rows[0]) != len(rows[1]):
            return ((), ())
        agreed = [
            all(part["text"].strip() and part["confidence"] >= 0.85 for part in pair)
            and literal(pair[0]["text"]) == literal(pair[1]["text"])
            for pair in zip(*rows, strict=True)
        ]
        return tuple(
            tuple(part if agreed[index] else None for index, part in enumerate(view))
            for view in rows
        )
    except (TypeError, ValueError, KeyError, IndexError, AttributeError):
        return ((), ())


def retained_request(part, position, image):
    if part is None:
        raise ValueError("Unqualified primary row cannot be retained")
    return {
        "retained_primary_row": position,
        "source_pixel_sha256": frame_digest(image),
    }


def checked_retained_request(request, part, position, *, pixels=None):
    if (
        part is None
        or not isinstance(request, dict)
        or set(request) != {"retained_primary_row", "source_pixel_sha256"}
        or type(request["retained_primary_row"]) is not int
        or request["retained_primary_row"] != position
        or not isinstance(request["source_pixel_sha256"], str)
        or not re.fullmatch(r"[a-f0-9]{64}", request["source_pixel_sha256"])
        or pixels is not None
        and request["source_pixel_sha256"] != frame_digest(pixels)
    ):
        raise ValueError("Retained primary row lost its literal or original pixels")
    return {key: part[key] for key in ("text", "confidence")}
