"""Resolve one current value to its real original cells without OCR or mutation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Upstream PyMuPDF has no typing marker; original geometry is runtime-validated.
import fitz  # type: ignore[import-untyped]

from patent_sar_extractor.core.pipeline_rules import _label_key

from .activity_focus_models import ActivityFocus
from .activity_provenance import SourceEvidence, metric_unit, source_evidence
from .artifact_values import page_number, text
from .correction_storage import CorrectionStorage, correction_source_fingerprint
from .corrections import apply_correction
from .errors import WebError
from .files import SafeFiles, records
from .models import Activity, Compound
from .storage import Store


def activity_source_keys(
    project: dict[str, Any], row: dict[str, Any], activities: list[Activity]
) -> list[str]:
    fingerprint = correction_source_fingerprint(project, row)
    try:
        return [
            hashlib.sha256(
                json.dumps(
                    [fingerprint, index, activity.model_dump()],
                    ensure_ascii=False,
                    sort_keys=True,
                    allow_nan=False,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()
            for index, activity in enumerate(activities)
        ]
    except (UnicodeEncodeError, ValueError) as exc:
        raise WebError(
            422, "invalid_activity", "Activity selection is invalid."
        ) from exc


@dataclass(frozen=True)
class FocusEvidence:
    compound_id: str
    activity_key: str
    cells: tuple[tuple[tuple[float, float, float, float], str | None], ...]


def matching_cells(
    source: SourceEvidence, owner: str, activity: Activity
) -> list[tuple[tuple[float, float, float, float], str | None]]:
    owner_ids = {
        _label_key(cell.value or "")
        for cell in source.cells
        if cell.name == "compound_id"
    }
    if owner_ids != {owner} or source.context != (
        activity.page,
        activity.target,
        activity.assay,
    ):
        return []
    return [
        (cell.bbox, source.geometry_space)
        for cell in source.cells
        if cell.bbox is not None
        and cell.name == activity.name
        and cell.value == text(activity.value, limit=1001)
        and metric_unit(cell.name) == activity.unit
    ]


def resolve_focus(
    store: Store, project_id: str, compound_id: str, key: str, page: int
) -> tuple[dict[str, Any], FocusEvidence]:
    with store.connect() as connection:
        connection.execute("BEGIN")
        project, row, saved = CorrectionStorage.context(
            connection, project_id, compound_id
        )
    raw = Compound.model_validate_json(row["payload"])
    effective = apply_correction(project, row, saved, raw.model_copy(deep=True))
    keys = activity_source_keys(project, row, effective.activities)
    if key not in keys:
        raise WebError(
            409,
            "activity_changed",
            "Activity or its source changed; refresh the results.",
        )
    activity = effective.activities[keys.index(key)]
    if activity.page != page:
        raise WebError(
            409,
            "activity_page_changed",
            "Selected activity belongs to another original page.",
        )
    collected: list[tuple[tuple[float, float, float, float], str | None]] = []
    # Only a verified original/run identity can supply a precise mark.
    if (
        project["run_root"]
        and project["sha256"]
        and project["sha256"] == project["expected_sha256"]
    ):
        payload = SafeFiles(Path(project["run_root"])).json(
            "activity/activity_data.json"
        )
        owner = _label_key(raw.id)
        for original in records(payload, "rows"):
            if not owner or _label_key(text(original.get("cpd")) or "") != owner:
                continue
            fallback = (
                page_number(original.get("page_no")),
                text(original.get("target")),
                text(original.get("assay")),
            )
            for source in source_evidence(
                original, fallback, page_count=project["page_count"]
            ):
                for cell in matching_cells(source, owner, activity):
                    if cell not in collected:
                        collected.append(cell)
                    if len(collected) > 80:
                        raise WebError(
                            422,
                            "activity_focus_limit",
                            "Activity focus exceeds its observation limit.",
                        )
    return project, FocusEvidence(compound_id, key, tuple(collected))


def rendered_focus(page: fitz.Page, focus: FocusEvidence) -> ActivityFocus:
    boxes: list[list[float]] = []
    for bounds, space in focus.cells:
        if space is None and page.rotation:
            # Legacy evidence did not declare native-vs-rendered orientation.
            continue
        rectangle = fitz.Rect(bounds)
        if space == "unrotated":
            rectangle *= page.rotation_matrix
        if (
            rectangle.is_empty
            or rectangle.is_infinite
            or rectangle.x0 < -1e-6
            or rectangle.y0 < -1e-6
            or rectangle.x1 > page.rect.width + 1e-6
            or rectangle.y1 > page.rect.height + 1e-6
        ):
            raise WebError(
                422,
                "invalid_activity_geometry",
                "Activity cell is outside the original page.",
            )
        converted = [
            min(page.rect.width, max(0.0, float(rectangle.x0))),
            min(page.rect.height, max(0.0, float(rectangle.y0))),
            min(page.rect.width, max(0.0, float(rectangle.x1))),
            min(page.rect.height, max(0.0, float(rectangle.y1))),
        ]
        if converted not in boxes:
            boxes.append(converted)
    return ActivityFocus(
        compound_id=focus.compound_id,
        activity_key=focus.activity_key,
        status="located" if boxes else "page_only",
        boxes=boxes,
        message=None if boxes else "该活性仅有来源页，缺少可核验的原文坐标。",
    )
