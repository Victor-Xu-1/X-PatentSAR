"""Original-document/crop identity and untrusted visible-label cache transport."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from patent_sar_extractor.contracts import (
    VISIBLE_LABEL_CACHE_SCHEMA,
    VISIBLE_LABEL_CACHE_SCHEMA_VERSION,
    VISIBLE_LABEL_OBSERVATION_VERSION,
    artifact_identity_matches,
)

logger = logging.getLogger(__name__)
_VISIBLE_LABEL_CACHE_VERSION = VISIBLE_LABEL_OBSERVATION_VERSION


def _has_original_identity(struct: dict) -> bool:
    value = struct.get("source_pdf_sha256")
    return isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value) is not None


def _structure_cache_signature(struct: dict) -> dict[str, Any]:
    """Fingerprint a segmented structure for visible-label cache safety.

    Structure IDs are assigned by segmentation order, so after changing crop
    regions the same Sxxxx may point to a different drawing. The visible-label
    labels may originate outside that crop. Reuse requires the entire original
    PDF, current page/geometry, and exact crop bytes, not merely a similar image.
    """
    bbox = [round(float(struct.get(key) or 0), 2) for key in ("x0", "y0", "x1", "y1")]
    image_path = str(struct.get("image_path") or "")
    image_sha256 = ""
    if image_path and os.path.exists(image_path):
        try:
            h = hashlib.sha256()
            with open(image_path, "rb") as f:
                for chunk in iter(lambda: f.read(1024 * 1024), b""):
                    h.update(chunk)
            image_sha256 = h.hexdigest()
        except (OSError, ValueError):
            image_sha256 = ""
    return {
        "page_no": int(struct.get("page_no") or 0),
        "bbox": bbox,
        "image_sha256": image_sha256,
        "source_pdf_sha256": str(struct.get("source_pdf_sha256") or ""),
    }


def _visible_cache_item_matches_structure(cache_item: Any, struct: dict) -> bool:
    if not isinstance(cache_item, dict):
        return False
    if not artifact_identity_matches(
        cache_item,
        VISIBLE_LABEL_CACHE_SCHEMA,
        VISIBLE_LABEL_CACHE_SCHEMA_VERSION,
    ):
        return False
    if cache_item.get("cache_complete") is not True:
        return False
    if (
        type(cache_item.get("cache_version")) is not int
        or cache_item["cache_version"] != _VISIBLE_LABEL_CACHE_VERSION
    ):
        return False
    cached_sig = cache_item.get("structure_signature")
    if not isinstance(cached_sig, dict):
        return False
    if not _has_original_identity(struct):
        return False
    current = _structure_cache_signature(struct)
    return (
        bool(re.fullmatch(r"[a-f0-9]{64}", current["image_sha256"]))
        and cached_sig == current
    )


def _filter_visible_label_cache_for_structures(
    cache: dict[str, dict] | None,
    processed_structures: list[dict],
) -> dict[str, dict]:
    """Keep only visible-label cache entries proven to match this run's crops."""
    if not cache:
        return {}
    struct_by_id = {
        str(struct.get("id") or ""): struct
        for struct in processed_structures
        if str(struct.get("id") or "")
    }
    filtered: dict[str, dict] = {}
    stale = 0
    for sid, item in cache.items():
        struct = struct_by_id.get(str(sid))
        if struct and _visible_cache_item_matches_structure(item, struct):
            filtered[str(sid)] = item
        else:
            stale += 1
    if stale:
        logger.info("   👁 丢弃不匹配的结构可见编号缓存: %d stale entries", stale)
    return filtered


def _normalise_visible_cache_item(cache_item: Any) -> list[dict[str, str]]:
    if not isinstance(cache_item, dict):
        return []
    raw_labels = cache_item.get("visible_label_candidates")
    if raw_labels is None:
        raw_labels = cache_item.get("visible_labels") or []
    candidates: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in raw_labels:
        if isinstance(item, dict):
            label = str(item.get("label") or "").strip()
            source = (
                str(item.get("source") or cache_item.get("source") or "cache").strip()
                or "cache"
            )
        else:
            label = str(item or "").strip()
            source = str(cache_item.get("source") or "cache").strip() or "cache"
        if not label:
            continue
        key = (label, source)
        if key in seen:
            continue
        seen.add(key)
        candidates.append({"label": label, "source": source})
    return candidates


def _labels_from_visible_cache_item(cache_item: Any) -> list[str]:
    labels: list[str] = []
    for item in _normalise_visible_cache_item(cache_item):
        label = str(item.get("label") or "").strip()
        if label and label not in labels:
            labels.append(label)
    return labels


def _visible_label_candidates_for_structure(
    struct: dict,
    visible_label_cache: dict[str, dict] | None = None,
) -> list[dict[str, str]]:
    cache_item = (visible_label_cache or {}).get(str(struct.get("id") or ""))
    if not _visible_cache_item_matches_structure(cache_item, struct):
        return []
    return _normalise_visible_cache_item(cache_item)


def _visible_label_cache_path(output_dir: str, profile: dict | None = None) -> Path:
    explicit = (profile or {}).get("visible_labels_path") or (profile or {}).get(
        "visible_label_cache"
    )
    if explicit:
        return Path(str(explicit))
    return Path(output_dir).parent / "visible_labels" / "visible_labels.json"


def _load_visible_label_cache(
    output_dir: str, profile: dict | None = None
) -> dict[str, dict]:
    """Load precomputed structure-label OCR cache when available.

    The cache is intentionally optional: if a run has not generated it yet,
    binder falls back to per-structure visual OCR. When present, however, these
    labels are the highest-priority binding evidence because they come from the
    drawing/label region itself rather than prose text.
    """
    candidates: list[Path] = []
    explicit = (profile or {}).get("visible_labels_path") or (profile or {}).get(
        "visible_label_cache"
    )
    if explicit:
        candidates.append(Path(str(explicit)))

    out = Path(output_dir)
    candidates.extend(
        [
            out / "visible_labels" / "visible_labels.json",
            out.parent / "visible_labels" / "visible_labels.json",
            out.parent.parent / "visible_labels" / "visible_labels.json",
        ]
    )

    seen: set[str] = set()
    for path in candidates:
        key = str(path)
        if key in seen or not path.is_file():
            continue
        seen.add(key)
        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except (OSError, TypeError, ValueError) as exc:
            logger.warning("   可见编号缓存读取失败 %s: %s", path, exc)
            continue
        if isinstance(payload, dict):
            logger.info(
                "   👁 加载结构可见编号缓存: %s (%d structures)", path, len(payload)
            )
            return payload
        logger.warning("   可见编号缓存格式不是 dict，忽略: %s", path)
    return {}
