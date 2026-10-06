"""Retain every unassociated source observation without inventing a compound."""

from __future__ import annotations

import hashlib
import json
from typing import Any
from urllib.parse import quote

from .artifact_values import box, page_number, text
from .errors import WebError
from .files import MAX_RECORDS, SafeFiles
from .models import Compound, Confidence, Recognition, Source


def unassociated_structures(
    project_id: str,
    structures: list[dict[str, Any]],
    represented: set[str],
    existing_ids: set[str],
    files: SafeFiles,
    *,
    verified_original: bool,
    page_count: int,
    crop_revision: str,
) -> tuple[list[dict[str, Any]], set[int]]:
    rows: list[dict[str, Any]] = []
    pages: set[int] = set()
    seen: set[str] = set()
    for structure in structures:
        structure_id = text(structure.get("structure_id"), limit=200)
        if structure_id and structure_id in seen:
            raise WebError(
                422,
                "ambiguous_structure",
                "Structure observation identifiers are duplicated; no source was silently selected.",
            )
        if structure_id:
            seen.add(structure_id)
        if structure_id and structure_id in represented:
            continue
        identity = structure_id or json.dumps(
            structure, sort_keys=True, ensure_ascii=False, allow_nan=False
        )
        base = "source-structure:" + hashlib.sha256(identity.encode()).hexdigest()[:32]
        record_id, suffix = base, 0
        while record_id in existing_ids:
            suffix += 1
            record_id = f"{base}:{suffix}"
        existing_ids.add(record_id)
        page = page_number(structure.get("page_no"))
        if page_count and page is not None and page > page_count:
            raise WebError(
                422,
                "invalid_artifact",
                "Structure source exceeds the original PDF page count.",
            )
        geometry = box({}, structure)
        image_path = text(structure.get("image_path"), limit=4096)
        flags = [
            "unassociated_structure",
            "activity_unassociated",
            "structure_number_unconfirmed",
        ]
        if image_path:
            try:
                with files.open(image_path, max_bytes=16 * 1024 * 1024):
                    pass
            except WebError:
                image_path = None
                flags.append("image_unavailable")
        has_crop = bool(image_path or (verified_original and geometry and page))
        if has_crop and page:
            pages.add(page)
        if not has_crop and "image_unavailable" not in flags:
            flags.append("image_unavailable")
        # Internal source ID is not a guessed printed compound/example number.
        reference = record_id.rsplit(":", 1)[-1][-8:]
        display_id = f"编号待确认 {structure_id or reference}"
        dto = Compound(
            id=record_id,
            display_id=display_id,
            structure_id=structure_id,
            structure_image_url=(
                f"/api/v1/projects/{project_id}/structures/{quote(record_id, safe='')}/image?revision={crop_revision}"
                if has_crop
                else None
            ),
            activities=[],
            source=Source(page=page, bbox=geometry),
            confidence=Confidence(
                level="review",
                reason="已保留结构原图；尚未证实原文编号，不能猜测或按活性集合分配编号。",
            ),
            recognition=Recognition(status="not_run"),
            flags=flags,
            record_kind="structure_only",
        )
        rows.append(
            {
                "dto": dto.model_dump(exclude={"admet", "descriptors", "correction"}),
                "image_path": image_path,
                "geometry_space": "rendered"
                if structure.get("bbox_pdf")
                else "unrotated",
            }
        )
        if len(existing_ids) > MAX_RECORDS:
            raise WebError(
                422, "artifact_limit", "Combined structure corpus exceeds its bound."
            )
    return rows, pages
