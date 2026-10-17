"""One source-image path/metadata resolver for the worker and stage fingerprints."""

from __future__ import annotations

import json
import os
from pathlib import Path

from .label_mask import source_geometry

WORKING_ROOT = str(Path.cwd())


def _resolved_path(value: str, base_dir: str) -> str:
    if not value or os.path.isabs(value):
        return value
    for root in (base_dir, WORKING_ROOT):
        candidate = os.path.join(root, value)
        if root and os.path.isfile(candidate):
            return os.path.abspath(candidate)
    return value


def _load_structure_image_lookup(base_dir: str = "") -> dict[str, dict]:
    lookup: dict[str, dict] = {}
    if not base_dir:
        return lookup
    base = Path(base_dir).resolve()
    candidate_roots = [base, base.parent, base.parent.parent]
    candidates = [root / "structures" / "metadata.json" for root in candidate_roots]
    for metadata_path in candidates:
        if not metadata_path.is_file():
            continue
        try:
            with open(metadata_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except (OSError, ValueError) as exc:
            raise ValueError("Structure metadata lookup is unreadable") from exc
        records = payload.get("structures") if isinstance(payload, dict) else payload
        if not isinstance(records, list):
            continue
        for rec in records:
            if not isinstance(rec, dict):
                continue
            sid = str(rec.get("structure_id") or rec.get("id") or "").strip()
            img = str(rec.get("image_path") or "").strip()
            if sid and img:
                lookup[sid] = {**rec, "image_path": _resolved_path(img, base_dir)}
        if lookup:
            break
    return lookup


def _is_clean_segmented_structure(rec: dict) -> bool:
    bbox = rec.get("bbox_pdf") or []
    if len(bbox) != 4:
        return False
    width = max(0.0, float(bbox[2]) - float(bbox[0]))
    height = max(0.0, float(bbox[3]) - float(bbox[1]))
    area = width * height
    aspect = width / max(height, 1.0)
    return area >= 4200 and width >= 100 and height >= 28 and aspect <= 5.5


def _choose_ocsr_image_path(
    item: dict, structure_lookup: dict[str, dict] | None = None
) -> str:
    """Choose the cleanest available image for OCSR."""
    ocsr_path = str(item.get("ocsr_image_path") or "").strip()
    if ocsr_path and os.path.isfile(ocsr_path):
        return ocsr_path

    image_path = str(
        item.get("image_path") or item.get("structure_image") or ""
    ).strip()
    rule = str(item.get("binding_rule") or "")
    source_sid = str(item.get("source_structure_id") or "").strip()
    if (
        structure_lookup
        and source_sid
        and (
            "expanded_strict_labels" in image_path
            or "merged_fragment" not in rule
            and str(item.get("expanded_from_fragment") or "")
        )
    ):
        # Expanded strict-label crops are visual evidence crops; use the original
        # segmented structure for OCSR when it is available.
        source_rec = structure_lookup.get(source_sid) or {}
        src_img = str(source_rec.get("image_path") or "").strip()
        if (
            _is_clean_segmented_structure(source_rec)
            and src_img
            and os.path.isfile(src_img)
        ):
            return src_img

    source_path = str(item.get("source_image_path") or "").strip()
    if source_path and os.path.isfile(source_path):
        return source_path

    if image_path and os.path.isfile(image_path):
        return image_path
    if image_path:
        return image_path
    return str(item.get("source_image_path") or item.get("ocsr_image_path") or "")


def resolve_image_paths(
    bindings: list, base_dir: str = "", *, attach_geometry: bool = True
) -> list:
    """Resolve image paths to absolute paths.

    Binding output may contain relative ``image_path`` values.
    Try to resolve them relative to base_dir or the caller's working directory.
    """
    structure_lookup = _load_structure_image_lookup(base_dir)

    def attach_source(item, image_path):
        item["ocsr_image_path"] = os.path.abspath(image_path)
        item.pop("_ocsr_source_geometry", None)
        item.pop("_ocsr_source_record", None)
        record = structure_lookup.get(
            str(item.get("source_structure_id") or item.get("structure_id") or "")
        )
        if record is not None:
            item["_ocsr_source_record"] = record
        if not attach_geometry:
            return
        if (
            record is not None
            and record.get("page_no") == item.get("page_no")
            and isinstance(item.get("exact_caption_evidence"), dict)
        ):
            try:
                frame = source_geometry(record, item["ocsr_image_path"])
            except (OSError, ValueError):
                # Optional caption removal may not erase/replace an unreadable
                # source. The converter still records the original image error.
                item["_ocsr_source_frame_unavailable"] = True
                frame = None
            if frame is not None:
                item["_ocsr_source_geometry"] = frame

    resolved = []
    for item in bindings:
        item = dict(item)  # Copy
        for field in (
            "ocsr_image_path",
            "source_image_path",
            "image_path",
            "structure_image",
        ):
            path = str(item.get(field) or "")
            if path:
                item[field] = _resolved_path(path, base_dir)
        img_path = _resolved_path(
            _choose_ocsr_image_path(item, structure_lookup), base_dir
        )

        if img_path and os.path.isfile(img_path):
            attach_source(item, img_path)
        resolved.append(item)

    return resolved
