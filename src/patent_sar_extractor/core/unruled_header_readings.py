"""Replay original column reads and pixel frames, without layout nomination."""

from .cell_frame_proof import valid_cell_frame
from .cell_text_proof import valid_text_reading
from .source_observations import project_source_observation
from .structure_table_headers import structure_header_role


def _reading_envelope(reading, xs, ys):
    if (
        not isinstance(reading, dict)
        or set(reading)
        != {"xs", "ys", "native_hints", "observations", "rendered_frames"}
        or reading["xs"] != xs
        or reading["ys"] != ys
    ):
        raise ValueError("Original header clipping windows were changed")
    observations, frames = reading["observations"], reading["rendered_frames"]
    if (
        not isinstance(observations, list)
        or len(observations) not in {1, 2}
        or any(not isinstance(o, dict) for o in observations)
        or not isinstance(frames, list)
    ):
        raise ValueError("Malformed original unruled header readings")
    hints = reading["native_hints"]
    if (
        not isinstance(hints, list)
        or len(hints) != 1
        or not isinstance(hints[0], list)
        or len(hints[0]) != len(xs) - 1
        or any(not isinstance(text, str) for text in hints[0])
    ):
        raise ValueError("Malformed original native header hints")
    methods = [o.get("method") for o in observations]
    native = methods == ["native_cells"]
    if (
        len(frames) != (0 if native else 2)
        or not native
        and methods != ["cell_ocr_400dpi", "cell_ocr_600dpi"]
    ):
        raise ValueError("Missing original unruled header pixel frames")
    for observed in observations:
        if (
            set(observed) != {"method", "matrix", "cells"}
            or not isinstance(observed["cells"], list)
            or len(observed["cells"]) != len(xs) - 1
            or not isinstance(observed["matrix"], list)
            or len(observed["matrix"]) != 1
            or not isinstance(observed["matrix"][0], list)
            or len(observed["matrix"][0]) != len(xs) - 1
        ):
            raise ValueError("Incomplete original unruled header columns")
    return observations, frames, hints[0], native


def original_header_readings(
    reading, xs, ys, sources, *, identity=structure_header_role
):
    """Return full raw headers only after every original column has been checked."""
    observations, frames, hints, native = _reading_envelope(reading, xs, ys)
    headers = []
    for col in range(len(xs) - 1):
        box = [xs[col], ys[0], xs[col + 1], ys[1]]
        raw = [project_source_observation(p, box) for p in sources]
        if hints[col] != next(p["text"] for p in raw if p["origin"] == "native"):
            raise ValueError("Native header hints differ from their original source")
        texts = []
        for index, observed in enumerate(observations):
            cell = observed["cells"][col]
            if (
                not isinstance(cell, dict)
                or cell.get("bbox") != box
                or cell.get("text") != observed["matrix"][0][col]
            ):
                raise ValueError("Original header cell lost its clipping scope")
            if native:
                if (
                    cell.get("method") != "native_cell"
                    or raw[0]["origin"] != "native"
                    or raw[0]["status"] != "qualified"
                    or cell.get("text") != raw[0]["text"]
                ):
                    return None
            elif (
                not isinstance(frames[index], list)
                or len(frames[index]) != len(xs) - 1
                or not valid_text_reading(cell, box, (400, 600)[index])
                or not valid_cell_frame(
                    frames[index][col], cell, box, (400, 600)[index]
                )
            ):
                return None
            texts.append(cell["text"])
        roles = {identity(text) for text in texts}
        if len(roles) != 1:
            return None
        if any(
            original["status"] == "qualified"
            and original["text"].strip()
            and identity(original["text"]) != next(iter(roles))
            for original in raw
        ):
            return None
        headers.append(texts[0])
    return headers
