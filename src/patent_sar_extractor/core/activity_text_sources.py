"""Literal declared-text source conservation; no parser, model or file reader."""

import math

from patent_sar_extractor.contracts import DECLARED_TEXT_SOURCE_VERSION

from .cell_frame_proof import inside_box, valid_cell_frame
from .cell_text_proof import valid_text_reading
from .source_cell_claims import cell_source_status, native_witness
from .source_geometry import source_layout
from .source_page_lines import native_page_lines, observed_page_text

MAX_TEXT_SOURCE_LINES = 4096


def same_text(left, right):
    # Ignore line-wrap whitespace, never merge separated digits or words.
    return (
        isinstance(left, str)
        and isinstance(right, str)
        and left.split() == right.split()
    )


def text_line_qualified(line):
    """A location proposal is not a read vote; retain all of its original reads."""
    if not isinstance(line, dict) or set(line) != {
        "nomination",
        "text",
        "bbox",
        "observations",
    }:
        return False
    text, bounds, readings = line["text"], line["bbox"], line["observations"]
    if (
        not isinstance(text, str)
        or not text.strip()
        or len(text) > 4096
        or not isinstance(line["nomination"], str)
        or len(line["nomination"]) > 4096
        or not isinstance(readings, list)
        or not 1 <= len(readings) <= 3
        or any(not isinstance(reading, dict) for reading in readings)
    ):
        return False
    primary = [reading for reading in readings if not native_witness(reading)]
    methods = [reading.get("method") for reading in primary]
    if methods == ["native_cell"]:
        reading = primary[0]
        return (
            "capture_error" not in reading
            and same_text(line["nomination"], text)
            and reading.get("bbox") == bounds
            and cell_source_status(reading) == "qualified"
            and same_text(
                " ".join(
                    token["text"] for token in reading["source_observation"]["tokens"]
                ),
                text,
            )
        )
    if methods != ["cell_ocr_400dpi", "cell_ocr_600dpi"]:
        return False
    for reading, dpi in zip(primary, (400, 600), strict=True):
        if (
            not same_text(reading.get("text"), text)
            or not valid_text_reading(reading, bounds, dpi)
            or not valid_cell_frame(reading.get("source_frame"), reading, bounds, dpi)
        ):
            return False
    for witness in readings:
        if native_witness(witness):
            if cell_source_status(witness) == "invalid":
                return False
            words = witness.get("text", "").split()
            actual = text.split()
            if words and not any(
                actual[i : i + len(words)] == words for i in range(len(actual))
            ):
                return False
    return True


def text_page_qualified(source, text):
    if (
        not isinstance(source, dict)
        or set(source) != {"version", "origin", "nomination_text", "page_size", "lines"}
        or type(source["version"]) is not int
        or source["version"] != DECLARED_TEXT_SOURCE_VERSION
        or not isinstance(source["origin"], str)
        or source["origin"] not in {"native", "located"}
        or not isinstance(source["nomination_text"], str)
        or len(source["nomination_text"]) > 100000
    ):
        return False
    size, lines = source["page_size"], source["lines"]
    if (
        not isinstance(size, list)
        or len(size) != 2
        or any(
            type(v) not in (int, float) or not math.isfinite(v) or not 0 < v <= 100000
            for v in size
        )
        or not isinstance(lines, list)
        or not 1 <= len(lines) <= MAX_TEXT_SOURCE_LINES
    ):
        return False
    seen = set()
    for line in lines:
        if not text_line_qualified(line) or not inside_box(line["bbox"], [0, 0, *size]):
            return False
        key = tuple(line["bbox"])
        if key in seen:
            return False
        seen.add(key)
        if source["origin"] == "native" and [
            r.get("method") for r in line["observations"]
        ] != ["native_cell"]:
            return False
    return (
        same_text(
            " ".join(line["nomination"] for line in lines), source["nomination_text"]
        )
        and observed_page_text(source) == text
        and (
            source["origin"] == "native"
            or any(
                r.get("method") == "cell_ocr_400dpi"
                for line in lines
                for r in line["observations"]
            )
        )
    )


def declared_text_cells(payload):
    """Same physical inventory as ordinary activity cells; no second replayer."""
    coverage = payload.get("coverage") or {}
    pages, sources = coverage.get("text_pages", {}), coverage.get("text_sources", {})
    if (
        not isinstance(pages, dict)
        or not isinstance(sources, dict)
        or set(sources) - set(pages)
    ):
        raise ValueError("Malformed declared-text physical source inventory")
    for key, source in sources.items():
        if (
            not isinstance(source, dict)
            or not isinstance(source.get("lines"), list)
            or len(source["lines"]) > MAX_TEXT_SOURCE_LINES
        ):
            raise ValueError("Malformed declared-text physical source")
        for line in source["lines"]:
            if (
                not isinstance(line, dict)
                or not isinstance(line.get("observations"), list)
                or len(line["observations"]) > 3
                or any(
                    not isinstance(reading, dict) for reading in line["observations"]
                )
            ):
                raise ValueError("Malformed declared-text physical readings")
            for reading in line["observations"]:
                yield int(key), reading


def original_text_pages_errors(coverage, document):
    pages, sources = coverage.get("text_pages", {}), coverage.get("text_sources", {})
    if set(pages) != set(sources):
        return ["Declared activity text has no complete physical source inventory."]
    for key, source in sources.items():
        if not text_page_qualified(source, pages[key]):
            return [
                "Declared activity text differs from its qualified source readings."
            ]
        number = int(key)
        if not 1 <= number <= len(document):
            return ["Declared activity text page is unavailable."]
        page = document[number - 1]
        if source["page_size"] != [page.rect.width, page.rect.height]:
            return ["Declared activity text has foreign page geometry."]
        layout = source_layout(page)
        native = layout.raster_bounds is None and same_text(
            page.get_text("text"), source["nomination_text"]
        )
        if source["origin"] != ("native" if native else "located"):
            return [
                "Declared activity text source mode differs from its actual original."
            ]
        if native:
            expected = [
                {"text": line["nomination"], "bbox": line["bbox"]}
                for line in source["lines"]
            ]
            if (
                layout.raster_bounds is not None
                or native_page_lines(layout) != expected
            ):
                return [
                    "Declared activity text differs from the actual original native page."
                ]
    return []
