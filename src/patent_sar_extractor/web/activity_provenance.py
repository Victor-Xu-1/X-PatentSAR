"""Single bounded parser for original activity contexts and cell evidence."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Literal

from ..core.activity_metadata import metadata_cell
from .activity_scope import ActivityScope, observed_scope
from .artifact_values import page_number, text
from .errors import WebError

ActivityContext = tuple[int | None, str | None, str | None]

# The current cell producer can retain source-window/frame, physical rows,
# detector metadata and a paired auxiliary packet together. Sixteen fields was
# a legacy transport bound, not a scientific qualification rule. Keep a finite
# envelope budget without stripping those original observations; core source
# replay remains the sole authority for whether their claims are qualified.
MAX_CELL_OBSERVATION_FIELDS = 32


@dataclass(frozen=True)
class CellEvidence:
    name: str
    value: str | None
    bbox: tuple[float, float, float, float] | None
    metadata: bool = False


@dataclass(frozen=True)
class SourceEvidence:
    context: ActivityContext
    cells: tuple[CellEvidence, ...]
    geometry_space: Literal["rendered", "unrotated"] | None
    conditions: tuple[tuple[str, str | None], ...] = ()
    scope: ActivityScope | None = None


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
        if (
            not isinstance(observation, dict)
            or len(observation) > MAX_CELL_OBSERVATION_FIELDS
        ):
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
    try:
        metadata = metadata_cell(cell)
    except (ValueError, TypeError, KeyError) as error:
        raise provenance_error() from error
    return CellEvidence(name, value, coordinates, metadata)


def source_evidence(
    row: dict[str, Any],
    fallback: ActivityContext,
    *,
    page_count: int = 0,
    document_sha256: str | None = None,
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
        table = provenance_text(source.get("table_id"), limit=300)
        scope = observed_scope(
            source, page, table, conditions, document_sha256=document_sha256
        )
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
                context,
                tuple(cell_evidence(cell) for cell in cells),
                space,
                conditions,
                scope,
            )
        )
    return result


def activity_contexts(
    row: dict[str, Any],
    fallback: ActivityContext,
    *,
    page_count: int,
    document_sha256: str | None = None,
) -> dict[tuple[str, str | None], list[tuple[ActivityContext, ActivityScope | None]]]:
    index: dict[
        tuple[str, str | None], dict[tuple[ActivityContext, ActivityScope | None], None]
    ] = {}
    for source in source_evidence(
        row, fallback, page_count=page_count, document_sha256=document_sha256
    ):
        for cell in source.cells:
            if cell.metadata:
                continue
            # Multiple OCR attempts prove one cell, not extra measurements.
            index.setdefault((cell.name, cell.value), {})[
                (source.context, source.scope)
            ] = None
    return {key: list(contexts) for key, contexts in index.items()}
