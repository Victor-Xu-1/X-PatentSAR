"""Single bounded parser for original activity contexts and cell evidence."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Literal

from .artifact_values import page_number, text
from .errors import WebError

ActivityContext = tuple[int | None, str | None, str | None]


@dataclass(frozen=True)
class CellEvidence:
    name: str
    value: str | None
    bbox: tuple[float, float, float, float] | None


@dataclass(frozen=True)
class SourceEvidence:
    context: ActivityContext
    cells: tuple[CellEvidence, ...]
    geometry_space: Literal["rendered", "unrotated"] | None
    conditions: tuple[tuple[str, str | None], ...] = ()


def provenance_error() -> WebError:
    return WebError(
        422,
        "invalid_artifact",
        "Activity provenance contains invalid or over-limit data.",
    )


def provenance_text(value: object, *, limit: int = 1000) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > limit or "\x00" in value:
        raise provenance_error()
    return value


def metric_unit(name: str) -> str | None:
    match = re.search(r"\(([^()]+)\)\s*$", name)
    return match.group(1) if match else None


def cell_evidence(cell: object) -> CellEvidence:
    if not isinstance(cell, dict):
        raise provenance_error()
    name = provenance_text(cell.get("field"), limit=300)
    value = text(cell.get("value"), limit=1001)
    if not name or (value is not None and len(value) > 1000):
        raise provenance_error()
    bounds = cell.get("bbox")
    if bounds is not None and (
        not isinstance(bounds, list)
        or len(bounds) != 4
        or not all(
            isinstance(x, (int, float))
            and not isinstance(x, bool)
            and 0 <= x <= 100000
            and math.isfinite(x)
            for x in bounds
        )
        or bounds[2] <= bounds[0]
        or bounds[3] <= bounds[1]
    ):
        raise provenance_error()
    observations = cell.get("observations", [])
    if not isinstance(observations, list) or len(observations) > 20:
        raise provenance_error()
    for observation in observations:
        if not isinstance(observation, dict) or len(observation) > 16:
            raise provenance_error()
        provenance_text(observation.get("method"), limit=300)
        provenance_text(observation.get("text"), limit=10000)
        confidence = observation.get("confidence")
        if confidence is not None and (
            not isinstance(confidence, (int, float))
            or isinstance(confidence, bool)
            or not 0 <= confidence <= 1
        ):
            raise provenance_error()
    coordinates = (
        (float(bounds[0]), float(bounds[1]), float(bounds[2]), float(bounds[3]))
        if bounds is not None
        else None
    )
    return CellEvidence(name, value, coordinates)


def source_evidence(
    row: dict[str, Any], fallback: ActivityContext, *, page_count: int = 0
) -> list[SourceEvidence]:
    sources = row.get("activity_sources")
    if sources is None:
        return []
    if not isinstance(sources, list) or len(sources) > 500:
        raise provenance_error()
    result: list[SourceEvidence] = []
    cell_count = 0
    for source in sources:
        if not isinstance(source, dict) or len(source) > 32:
            raise provenance_error()
        raw_page = source.get("page_no", fallback[0])
        if raw_page is not None and (
            not isinstance(raw_page, (int, str))
            or isinstance(raw_page, bool)
            or raw_page == 0
        ):
            raise provenance_error()
        page = page_number(raw_page)
        if page and page_count and page > page_count:
            raise provenance_error()
        context = (
            page,
            provenance_text(source["target"], limit=300)
            if "target" in source
            else fallback[1],
            provenance_text(source["assay"]) if "assay" in source else fallback[2],
        )
        conditions = tuple(
            (key, provenance_text(source[key], limit=1000))
            for key in (
                "cell_line",
                "construct",
                "duration",
                "treatment_duration",
                "timepoint",
                "batch",
            )
            if key in source
        )
        provenance_text(source.get("table_id"), limit=300)
        for field in ("row", "pair"):
            number = source.get(field)
            if number is not None and (
                not isinstance(number, int)
                or isinstance(number, bool)
                or not 0 <= number <= 1000000
            ):
                raise provenance_error()
        cells = source.get("cells", [])
        if not isinstance(cells, list) or len(cells) > 500:
            raise provenance_error()
        cell_count += len(cells)
        if cell_count > 2000:
            raise provenance_error()
        space = source.get("geometry_space")
        if space not in (None, "rendered", "unrotated"):
            raise provenance_error()
        result.append(
            SourceEvidence(
                context, tuple(cell_evidence(cell) for cell in cells), space, conditions
            )
        )
    return result


def activity_contexts(
    row: dict[str, Any], fallback: ActivityContext, *, page_count: int
) -> dict[tuple[str, str | None], list[ActivityContext]]:
    index: dict[tuple[str, str | None], dict[ActivityContext, None]] = {}
    for source in source_evidence(row, fallback, page_count=page_count):
        for cell in source.cells:
            # Multiple OCR attempts prove one cell, not extra measurements.
            index.setdefault((cell.name, cell.value), {})[source.context] = None
    return {key: list(contexts) for key, contexts in index.items()}
