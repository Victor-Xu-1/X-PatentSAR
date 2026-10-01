"""Versioned visible-label observations and exact crop identity."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from datetime import (
    datetime,
)
from pathlib import (
    Path,
)
from typing import (
    Any,
    Dict,
    List,
    Optional,
    Tuple,
)

from patent_sar_extractor.contracts import (
    VISIBLE_LABEL_CACHE_SCHEMA,
    VISIBLE_LABEL_CACHE_SCHEMA_VERSION,
    artifact_identity,
    artifact_identity_matches,
)

from .binding_geometry import (
    _group_structures_by_row,
    _row_for_structure,
)
from .binding_labels import (
    _VISIBLE_LABEL_SOURCE_RANK,
    _base_cpd_num,
    _binding_label_key,
    _cpd_label_key,
    _cpd_sort_key,
    _is_truncated_visible_prefix,
    _labels_from_ocr_text,
    _labels_from_ocr_texts,
    _nearby_exact_product_label,
    _nearby_ocr_label_kind,
    _normalise_compound_label,
    _product_context_distance,
)
from .binding_ocr import (
    _allow_tesseract_fallback,
    _paddlex_ocr_texts_batch,
    _paddlex_ocr_texts_from_image,
    fitz,
    paddlex_available,
)

logger = logging.getLogger(__name__)


_VISIBLE_LABEL_CACHE_VERSION = 7


_CD3_LINE_RE = re.compile(r"(?:CD\s*[_₃3]?3?|C\s*D\s*[_₃3]?3)", re.IGNORECASE)


def _structure_cache_signature(struct: Dict) -> Dict[str, Any]:
    """Fingerprint a segmented structure for visible-label cache safety.

    Structure IDs are assigned by segmentation order, so after changing crop
    regions the same Sxxxx may point to a different drawing. The visible-label
    cache is only safe to reuse when the current page, geometry, and image bytes
    match the cached structure.
    """
    bbox = [round(float(struct.get(key) or 0), 2) for key in ("x0", "y0", "x1", "y1")]
    image_path = str(struct.get("image_path") or "")
    image_sha1 = ""
    if image_path and os.path.exists(image_path):
        try:
            h = hashlib.sha1()
            with open(image_path, "rb") as f:
                for chunk in iter(lambda: f.read(1024 * 1024), b""):
                    h.update(chunk)
            image_sha1 = h.hexdigest()
        except Exception:
            image_sha1 = ""
    return {
        "page_no": int(struct.get("page_no") or 0),
        "bbox": bbox,
        "image_sha1": image_sha1,
    }


def _visible_cache_item_matches_structure(cache_item: Any, struct: Dict) -> bool:
    if not isinstance(cache_item, dict):
        return False
    if not artifact_identity_matches(
        cache_item,
        VISIBLE_LABEL_CACHE_SCHEMA,
        VISIBLE_LABEL_CACHE_SCHEMA_VERSION,
    ):
        return False
    if not cache_item.get("cache_complete"):
        return False
    if int(cache_item.get("cache_version") or 0) < _VISIBLE_LABEL_CACHE_VERSION:
        return False
    cached_sig = cache_item.get("structure_signature")
    if not isinstance(cached_sig, dict):
        return False
    return cached_sig == _structure_cache_signature(struct)


def _filter_visible_label_cache_for_structures(
    cache: Optional[Dict[str, Dict]],
    processed_structures: List[Dict],
) -> Dict[str, Dict]:
    """Keep only visible-label cache entries proven to match this run's crops."""
    if not cache:
        return {}
    struct_by_id = {
        str(struct.get("id") or ""): struct
        for struct in processed_structures
        if str(struct.get("id") or "")
    }
    filtered: Dict[str, Dict] = {}
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


def _direct_labels_from_structure_image(struct: Dict) -> List[str]:
    """OCR labels embedded in/under a structure crop.

    Some final product labels are cropped together with the drawing, so whole
    page OCR may miss them. Keep this narrow: only bare 2-3 digit labels are
    accepted; lettered labels such as 17h/44b remain intermediates.
    """
    image_path = str(struct.get("image_path") or "")
    if not image_path or not os.path.exists(image_path):
        return []
    try:
        from PIL import Image

        if _allow_tesseract_fallback():
            import pytesseract  # type: ignore
        else:
            pytesseract = None
    except Exception:
        return []

    labels: List[str] = []
    try:
        img = Image.open(image_path).convert("L")
        width, height = img.size
        # Only inspect the bottom label band. OCR-ing the whole structure
        # catches reagent numbers, page fragments, or substituent annotations
        # and can steal a binding from the actual compound label.
        crops = [
            img.crop((0, int(height * 0.72), width, height)),
            img.crop(
                (int(width * 0.15), int(height * 0.62), int(width * 0.85), height)
            ),
        ]
        for crop in crops:
            ocr_texts = _paddlex_ocr_texts_from_image(crop)
            if not ocr_texts:
                if pytesseract is None:
                    continue
                text = pytesseract.image_to_string(crop, lang="eng", config="--psm 6")
                ocr_texts = [text]
            for text in ocr_texts:
                for value in _labels_from_ocr_text(str(text or "")):
                    if value not in labels:
                        labels.append(value)
    except Exception:
        return labels
    return labels


def _normalise_visible_cache_item(cache_item: Any) -> List[Dict[str, str]]:
    if not isinstance(cache_item, dict):
        return []
    raw_labels = cache_item.get("visible_label_candidates")
    if raw_labels is None:
        raw_labels = cache_item.get("visible_labels") or []
    candidates: List[Dict[str, str]] = []
    seen: set[Tuple[str, str]] = set()
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


def _labels_from_visible_cache_item(cache_item: Any) -> List[str]:
    labels: List[str] = []
    for item in _normalise_visible_cache_item(cache_item):
        label = str(item.get("label") or "").strip()
        if label and label not in labels:
            labels.append(label)
    return labels


def _refine_visible_label_cache_with_page_ocr(
    processed_structures: List[Dict],
    visible_label_cache: Optional[Dict[str, Dict]],
    ocr_line_map: Optional[Dict[int, List[Any]]],
    output_dir: str,
    profile: Optional[dict] = None,
) -> Dict[str, Dict]:
    """Use full-page OCR label rows to restore suffixes lost by tight crops."""
    if not visible_label_cache or not ocr_line_map:
        return visible_label_cache or {}
    lines_by_page = _normalise_ocr_line_map(ocr_line_map)
    if not lines_by_page:
        return visible_label_cache
    struct_by_id = {
        str(struct.get("id") or ""): struct for struct in processed_structures
    }
    rows_by_page: Dict[int, List[List[Dict]]] = {}
    for page_no in sorted(
        {int(struct.get("page_no") or 0) for struct in processed_structures}
    ):
        rows_by_page[page_no] = _group_structures_by_row(
            [
                struct
                for struct in processed_structures
                if int(struct.get("page_no") or 0) == page_no
            ],
            y_threshold=55.0,
        )

    refined: Dict[str, Dict] = {}
    changed = 0
    for sid, cache_item in visible_label_cache.items():
        item = dict(cache_item) if isinstance(cache_item, dict) else {}
        struct = struct_by_id.get(str(sid))
        if not struct or not item:
            changed += 1
            continue
        if not _visible_cache_item_matches_structure(item, struct):
            changed += 1
            continue
        candidates: List[Dict[str, str]] = []
        for candidate in _normalise_visible_cache_item(item):
            label = _normalise_compound_label(str(candidate.get("label") or ""))
            key = _cpd_label_key(label)
            if not key:
                continue
            base_num = _base_cpd_num(key)
            base_key = str(base_num) if base_num is not None else key
            nearby_kind = _nearby_ocr_label_kind(struct, base_key, lines_by_page)
            if nearby_kind == "racemic":
                changed += 1
                continue
            exact = _nearby_exact_product_label(
                struct,
                base_key,
                lines_by_page,
                row=_row_for_structure(struct, rows_by_page),
            )
            if (
                exact
                and exact != key
                and (
                    _base_cpd_num(exact) == base_num
                    or _is_truncated_visible_prefix(exact, key)
                    or _is_truncated_visible_prefix(key, exact)
                )
            ):
                label = exact
                changed += 1
            updated = dict(candidate)
            updated["label"] = label
            candidates.append(updated)
        if candidates:
            item["visible_label_candidates"] = candidates
            item["visible_labels"] = []
            for candidate in candidates:
                label = str(candidate.get("label") or "").strip()
                if label and label not in item["visible_labels"]:
                    item["visible_labels"].append(label)
            item["page_ocr_refined"] = True
        refined[str(sid)] = item

    if changed:
        try:
            path = _visible_label_cache_path(output_dir, profile)
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(refined, f, ensure_ascii=False, indent=2)
            logger.info(
                "   👁 页面OCR校正可见编号缓存: %d candidates -> %s", changed, path
            )
        except Exception as exc:
            logger.warning("   页面OCR校正可见编号缓存写入失败: %s", exc)
    return refined


def _visible_label_candidates_for_structure(
    struct: Dict,
    visible_label_cache: Optional[Dict[str, Dict]] = None,
) -> List[Dict[str, str]]:
    cache_item = (visible_label_cache or {}).get(str(struct.get("id") or ""))
    if not _visible_cache_item_matches_structure(cache_item, struct):
        return []
    return _normalise_visible_cache_item(cache_item)


def _annotate_bindings_with_visible_labels(
    bindings: List[Dict],
    visible_label_cache: Optional[Dict[str, Dict]],
) -> List[Dict]:
    if not bindings or not visible_label_cache:
        return bindings
    annotated: List[Dict] = []
    for binding in bindings:
        item = dict(binding)
        sid = str(item.get("source_structure_id") or item.get("structure_id") or "")
        candidates = _normalise_visible_cache_item((visible_label_cache or {}).get(sid))
        if candidates:
            labels: List[str] = []
            sources: List[str] = []
            label_sources: Dict[str, List[str]] = {}
            normalized_candidates: List[Dict[str, str]] = []
            for candidate in candidates:
                label = _normalise_compound_label(str(candidate.get("label") or ""))
                if label and label not in labels:
                    labels.append(label)
                source = str(candidate.get("source") or "")
                if source and source not in sources:
                    sources.append(source)
                if label:
                    label_sources.setdefault(label, [])
                    if source and source not in label_sources[label]:
                        label_sources[label].append(source)
                    normalized_candidates.append({"label": label, "source": source})
            item["visible_labels"] = labels
            item["visible_label_candidates"] = normalized_candidates
            item["visible_label_sources"] = label_sources
            if not item.get("visible_label") and len(labels) == 1:
                item["visible_label"] = labels[0]
            if not item.get("visible_label_crop_source") and sources:
                item["visible_label_crop_source"] = sources[0]
        annotated.append(item)
    return annotated


def _contextual_visible_label_candidates(
    struct: Dict,
    candidates: List[Dict[str, str]],
    active_keys_or_bases,
    pages_text: Optional[Dict[int, str]],
    max_context_distance: int = 1,
    lines_by_page: Optional[Dict[int, List[Tuple[float, str]]]] = None,
    row: Optional[List[Dict]] = None,
) -> List[Dict[str, Any]]:
    """Return visual label candidates proven by activity set and context.

    OCR can read multiple numbers from a wide crop. Treat the label as binding
    evidence only when it is active and the page text has nearby product context
    for that exact number. This prevents neighboring/intermediate labels from
    hijacking a final compound.
    """
    ranked: List[Tuple[int, int, int, int, int, Dict[str, Any]]] = []
    page_no = int(struct.get("page_no") or 0)
    width = max(0.0, float(struct.get("x1") or 0) - float(struct.get("x0") or 0))
    height = max(0.0, float(struct.get("y1") or 0) - float(struct.get("y0") or 0))
    route_like = 1 if (height > 0 and width / max(height, 1.0) > 5.5) else 0
    multi_label = (
        1
        if len(
            {str(c.get("label") or "").strip() for c in candidates if c.get("label")}
        )
        > 1
        else 0
    )
    active_keys = {str(item).upper() for item in (active_keys_or_bases or set())}
    visible_candidate_bases: List[int] = []
    for candidate in candidates:
        label_key = _cpd_label_key(
            _normalise_compound_label(str(candidate.get("label") or "").strip())
        )
        base = _base_cpd_num(label_key)
        if base is not None:
            visible_candidate_bases.append(base)
    max_visible_candidate_base = (
        max(visible_candidate_bases) if visible_candidate_bases else 0
    )
    for candidate in candidates:
        label = _normalise_compound_label(str(candidate.get("label") or "").strip())
        if not re.fullmatch(r"[1-9]\d{0,2}[A-Z]?", label, re.IGNORECASE):
            continue
        label_key = _cpd_label_key(label)
        if label_key not in active_keys:
            continue
        compound_num = _base_cpd_num(label) or 0
        exact_label = _nearby_exact_product_label(
            struct, label_key, lines_by_page, row=row
        )
        if exact_label and exact_label != label_key:
            continue
        if multi_label and compound_num <= 20 and exact_label != label_key:
            continue
        distance = 0
        if pages_text is not None:
            distance = _product_context_distance(pages_text, page_no, compound_num)
            if distance > max_context_distance:
                continue
        source = str(candidate.get("source") or "ocr").strip() or "ocr"
        item: Dict[str, Any] = {
            "label": label,
            "label_key": label_key,
            "source": source,
            "product_context_distance": distance,
            "multi_label_crop": bool(multi_label),
        }
        internal_low_rank = (
            1
            if (
                multi_label
                and compound_num <= 20
                and max_visible_candidate_base >= max(50, compound_num + 30)
            )
            else 0
        )
        ranked.append(
            (
                internal_low_rank,
                distance,
                _VISIBLE_LABEL_SOURCE_RANK.get(source, 99),
                multi_label,
                route_like,
                item,
            )
        )
    ranked.sort(key=lambda row: row[:4])
    if not ranked:
        return []
    # One structure crop should contribute one final compound. If a wide crop
    # sees neighbors too, keep only the context-proven best label.
    return [ranked[0][5]]


def _visible_label_cache_path(output_dir: str, profile: Optional[dict] = None) -> Path:
    explicit = (profile or {}).get("visible_labels_path") or (profile or {}).get(
        "visible_label_cache"
    )
    if explicit:
        return Path(str(explicit))
    return Path(output_dir).parent / "visible_labels" / "visible_labels.json"


def _visible_label_crop_tasks_from_page_image(
    struct: Dict, include_wide: bool = True
) -> List[Tuple[str, Any]]:
    raw = struct.get("struct") or {}
    bbox = raw.get("bbox") or []
    if len(bbox) != 4:
        return []

    image_path = str(struct.get("image_path") or "")
    if not image_path:
        return []
    page_no = int(struct.get("page_no") or 0)
    page_image = Path(image_path).with_name(f"page_{page_no:03d}.png")
    if not page_image.is_file():
        return []

    try:
        from PIL import Image, ImageEnhance, ImageOps
    except Exception:
        return []

    try:
        img = Image.open(page_image).convert("L")
        x0, y0, x1, y1 = [int(round(float(v))) for v in bbox]
    except Exception:
        return []

    width = max(1, x1 - x0)
    height = max(1, y1 - y0)
    strict_boxes = [
        (
            x0 + int(0.25 * width),
            y1 - int(0.05 * height),
            x1 - int(0.25 * width),
            y1 + max(16, int(0.16 * height)),
        ),
        (x0 + int(0.25 * width), y0 + int(0.70 * height), x1 - int(0.25 * width), y1),
        (
            x0 + int(0.35 * width),
            y1 - int(0.02 * height),
            x1 - int(0.35 * width),
            y1 + max(20, int(0.18 * height)),
        ),
    ]
    normal_boxes = [
        (
            x0 + int(0.18 * width),
            y0 + int(0.58 * height),
            x1 - int(0.18 * width),
            y1 + max(8, int(0.10 * height)),
        ),
        (
            x0 + int(0.05 * width),
            y0 + int(0.52 * height),
            x1 - int(0.05 * width),
            y1 + max(18, int(0.22 * height)),
        ),
    ]
    wide_boxes = (
        [
            (x0, y0 + int(0.45 * height), x1, y1 + max(28, int(0.32 * height))),
            (
                x0 + int(0.10 * width),
                y0 + int(0.35 * height),
                x1 - int(0.10 * width),
                y1 + max(36, int(0.38 * height)),
            ),
        ]
        if include_wide
        else []
    )

    tasks: List[Tuple[str, Any]] = []
    source_boxes = [("page_strict", strict_boxes)]
    if include_wide:
        source_boxes.append(("page_wide", normal_boxes + wide_boxes))
    for source, boxes in source_boxes:
        for box in boxes:
            left = max(0, box[0])
            top = max(0, box[1])
            right = min(img.width, box[2])
            bottom = min(img.height, box[3])
            if right - left <= 5 or bottom - top <= 5:
                continue
            try:
                crop = img.crop((left, top, right, bottom))
                crop = ImageOps.autocontrast(crop)
                crop = crop.resize((crop.width * 3, crop.height * 3))
                crop = ImageEnhance.Sharpness(crop).enhance(2.0)
            except Exception:
                continue
            tasks.append((source, crop))
    return tasks


def _visible_label_crop_tasks_from_structure_image(
    struct: Dict,
) -> List[Tuple[str, Any]]:
    image_path = str(struct.get("image_path") or "")
    if not image_path or not os.path.exists(image_path):
        return []
    try:
        from PIL import Image
    except Exception:
        return []
    try:
        img = Image.open(image_path).convert("L")
        width, height = img.size
        return [
            ("direct", img.crop((0, int(height * 0.72), width, height))),
            (
                "direct",
                img.crop(
                    (int(width * 0.15), int(height * 0.62), int(width * 0.85), height)
                ),
            ),
        ]
    except Exception:
        return []


def _precompute_visible_label_cache(
    processed_structures: List[Dict],
    output_dir: str,
    profile: Optional[dict],
    existing_cache: Optional[Dict[str, Dict]],
    workers: int = 4,
) -> Dict[str, Dict]:
    """Precompute visible structure labels once and persist them for reuse."""
    cache = _filter_visible_label_cache_for_structures(
        existing_cache, processed_structures
    )
    path = _visible_label_cache_path(output_dir, profile)
    pending = [
        struct
        for struct in processed_structures
        if str(struct.get("id") or "")
        and not _visible_cache_item_matches_structure(
            cache.get(str(struct.get("id") or "")), struct
        )
    ]
    if not pending:
        logger.info("   👁 结构可见编号缓存已完整: %s (%d structures)", path, len(cache))
        return cache

    logger.info(
        "   👁 批量PaddleX识别结构可见编号: %d structures, workers=%d",
        len(pending),
        max(1, int(workers or 1)),
    )

    def _run_stage(
        stage_name: str, task_builder
    ) -> Tuple[Dict[str, List[str]], Dict[str, int]]:
        flat_images: List[Any] = []
        flat_meta: List[Tuple[str, str]] = []
        attempts: Dict[str, int] = {}
        for struct in pending:
            sid = str(struct.get("id") or "")
            if not sid:
                continue
            tasks = task_builder(struct)
            attempts[sid] = attempts.get(sid, 0) + len(tasks)
            for source, crop in tasks:
                flat_meta.append((sid, source))
                flat_images.append(crop)
        if not flat_images:
            return {}, attempts
        ocr_results = _paddlex_ocr_texts_batch(
            flat_images, workers=workers, timeout=12.0
        )
        labels_by_sid: Dict[str, List[str]] = {}
        for (sid, source), ocr_texts in zip(flat_meta, ocr_results):
            for label in _labels_from_ocr_texts(ocr_texts):
                entry = f"{label}|{source}"
                if entry not in labels_by_sid.setdefault(sid, []):
                    labels_by_sid[sid].append(entry)
        logger.info(
            "   👁 %s OCR: %d crops, %d structures with labels",
            stage_name,
            len(flat_images),
            len(labels_by_sid),
        )
        return labels_by_sid, attempts

    strict_by_sid, strict_attempts = _run_stage(
        "strict",
        lambda struct: [
            task
            for task in _visible_label_crop_tasks_from_page_image(
                struct, include_wide=False
            )
            if task[0] == "page_strict"
        ],
    )
    unresolved_after_strict = {
        str(struct.get("id") or "")
        for struct in pending
        if str(struct.get("id") or "")
        and str(struct.get("id") or "") not in strict_by_sid
    }

    def _wide_direct_tasks(struct: Dict) -> List[Tuple[str, Any]]:
        sid = str(struct.get("id") or "")
        if sid not in unresolved_after_strict:
            return []
        page_tasks = [
            task
            for task in _visible_label_crop_tasks_from_page_image(
                struct, include_wide=True
            )
            if task[0] == "page_wide"
        ]
        return page_tasks + _visible_label_crop_tasks_from_structure_image(struct)

    wide_by_sid, wide_attempts = _run_stage("wide/direct", _wide_direct_tasks)

    if paddlex_available() is False:
        logger.warning("   PaddleX OCR不可用，跳过可见编号缓存写入，避免缓存空结果")
        return cache

    now = datetime.now().strftime("%Y%m%d_%H%M%S")
    for struct in pending:
        sid = str(struct.get("id") or "")
        if not sid:
            continue
        candidates: List[Dict[str, str]] = []
        seen_labels: set[str] = set()
        for packed in (strict_by_sid.get(sid) or []) + (wide_by_sid.get(sid) or []):
            label, source = packed.split("|", 1)
            if label in seen_labels:
                continue
            seen_labels.add(label)
            candidates.append({"label": label, "source": source})
        candidates.sort(
            key=lambda item: (
                _VISIBLE_LABEL_SOURCE_RANK.get(str(item.get("source") or ""), 99),
                _cpd_sort_key(str(item.get("label") or "")),
            )
        )
        cache[sid] = {
            **artifact_identity(
                VISIBLE_LABEL_CACHE_SCHEMA, VISIBLE_LABEL_CACHE_SCHEMA_VERSION
            ),
            "structure_id": sid,
            "page_no": int(struct.get("page_no") or 0),
            "structure_signature": _structure_cache_signature(struct),
            "visible_labels": [item["label"] for item in candidates],
            "visible_label_candidates": candidates,
            "ocr_backend": "paddlex",
            "cache_version": _VISIBLE_LABEL_CACHE_VERSION,
            "cache_complete": True,
            "ocr_attempts": int(
                strict_attempts.get(sid, 0) + wide_attempts.get(sid, 0)
            ),
            "updated_at": now,
        }

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
        label_count = sum(
            1 for item in cache.values() if _labels_from_visible_cache_item(item)
        )
        logger.info(
            "   👁 写入结构可见编号缓存: %s (%d/%d with labels)",
            path,
            label_count,
            len(cache),
        )
    except Exception as exc:
        logger.warning("   可见编号缓存写入失败 %s: %s", path, exc)
    return cache


def _ocr_visible_label_band(doc, struct: Dict, dpi: int = 450) -> List[str]:
    """OCR the visual label band around a structure on the original PDF page.

    This deliberately uses the page image, not surrounding text blocks. It
    expands slightly below the structure because final labels are often printed
    just outside the structure crop.
    """
    page_no = int(struct.get("page_no") or 0)
    if page_no < 1 or page_no > len(doc):
        return []
    try:
        if _allow_tesseract_fallback():
            import pytesseract  # type: ignore
        else:
            pytesseract = None
        from io import BytesIO

        from PIL import Image
    except Exception:
        return []

    x0 = float(struct.get("x0") or 0)
    y0 = float(struct.get("y0") or 0)
    x1 = float(struct.get("x1") or x0)
    y1 = float(struct.get("y1") or y0)
    width = max(1.0, x1 - x0)
    height = max(1.0, y1 - y0)
    page = doc[page_no - 1]
    labels: List[str] = []

    clips = [
        # Bottom-center strip, often where the compound number is printed.
        fitz.Rect(
            max(0, x0 + 0.18 * width),
            max(0, y1 - max(18.0, 0.22 * height)),
            min(page.rect.width, x1 - 0.18 * width),
            min(page.rect.height, y1 + max(32.0, 0.28 * height)),
        ),
        # A slightly wider lower band catches labels just below the crop while
        # still avoiding prose text and reaction annotations elsewhere.
        fitz.Rect(
            max(0, x0 + 0.08 * width),
            max(0, y1 - max(12.0, 0.12 * height)),
            min(page.rect.width, x1 - 0.08 * width),
            min(page.rect.height, y1 + max(42.0, 0.34 * height)),
        ),
    ]
    for clip in clips:
        if clip.width <= 3 or clip.height <= 3:
            continue
        try:
            pix = page.get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72), clip=clip)
            img = Image.open(BytesIO(pix.tobytes("png"))).convert("L")
            ocr_texts = _paddlex_ocr_texts_from_image(img)
            if not ocr_texts:
                if pytesseract is None:
                    continue
                text = pytesseract.image_to_string(
                    img,
                    lang="eng",
                    config="--psm 6 -c tessedit_char_whitelist=0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-",
                )
                ocr_texts = [text]
        except Exception:
            continue
        for text in ocr_texts:
            for value in _labels_from_ocr_text(str(text or "")):
                if value not in labels:
                    labels.append(value)
    return labels


def _ocr_visible_label_band_from_page_image(
    struct: Dict, wide: bool = False
) -> List[str]:
    """OCR the label band using the rendered page image and image-coordinate bbox.

    Step 6 stores both PDF coordinates and rendered-page pixel coordinates. The
    small bold labels under Chinese patent structures are often much more
    readable on the rendered page image than through PDF text extraction or a
    PDF-coordinate clip. This intentionally inspects only the lower part of the
    structure crop, where the visual compound label is printed.
    """
    raw = struct.get("struct") or {}
    bbox = raw.get("bbox") or []
    if len(bbox) != 4:
        return []

    image_path = str(struct.get("image_path") or "")
    if not image_path:
        return []
    page_no = int(struct.get("page_no") or 0)
    page_image = Path(image_path).with_name(f"page_{page_no:03d}.png")
    if not page_image.is_file():
        return []

    try:
        if _allow_tesseract_fallback():
            import pytesseract  # type: ignore
        else:
            pytesseract = None
        from PIL import Image, ImageEnhance, ImageOps
    except Exception:
        return []

    try:
        img = Image.open(page_image).convert("L")
    except Exception:
        return []

    try:
        x0, y0, x1, y1 = [int(round(float(v))) for v in bbox]
    except Exception:
        return []
    width = max(1, x1 - x0)
    height = max(1, y1 - y0)

    def _read_boxes(crop_boxes: List[Tuple[int, int, int, int]]) -> List[str]:
        labels: List[str] = []
        for box in crop_boxes:
            left = max(0, box[0])
            top = max(0, box[1])
            right = min(img.width, box[2])
            bottom = min(img.height, box[3])
            if right - left <= 5 or bottom - top <= 5:
                continue
            try:
                crop = img.crop((left, top, right, bottom))
                crop = ImageOps.autocontrast(crop)
                crop = crop.resize((crop.width * 3, crop.height * 3))
                crop = ImageEnhance.Sharpness(crop).enhance(2.0)
            except Exception:
                continue
            ocr_texts = _paddlex_ocr_texts_from_image(crop)
            if not ocr_texts:
                if pytesseract is None:
                    continue
                try:
                    text = pytesseract.image_to_string(
                        crop,
                        lang="eng",
                        config="--psm 6 -c tessedit_char_whitelist=0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-",
                    )
                    ocr_texts = [text]
                except Exception:
                    continue
            for text in ocr_texts:
                for value in _labels_from_ocr_text(str(text or "")):
                    if value not in labels:
                        labels.append(value)
        return labels

    strict_boxes = [
        # Read the printed label itself, not surrounding chemistry/prose. This
        # prevents 101-style labels from being misread as another active number.
        (
            x0 + int(0.25 * width),
            y1 - int(0.05 * height),
            x1 - int(0.25 * width),
            y1 + max(16, int(0.16 * height)),
        ),
        (x0 + int(0.25 * width), y0 + int(0.70 * height), x1 - int(0.25 * width), y1),
        (
            x0 + int(0.35 * width),
            y1 - int(0.02 * height),
            x1 - int(0.35 * width),
            y1 + max(20, int(0.18 * height)),
        ),
    ]
    strict_labels = _read_boxes(strict_boxes)
    if strict_labels:
        return strict_labels

    crop_boxes = [
        # Most labels sit inside the lower third of the structure crop.
        (
            x0 + int(0.18 * width),
            y0 + int(0.58 * height),
            x1 - int(0.18 * width),
            y1 + max(8, int(0.10 * height)),
        ),
        # Wider lower band catches labels below long horizontal structures, but
        # only after strict label boxes fail.
        (
            x0 + int(0.05 * width),
            y0 + int(0.52 * height),
            x1 - int(0.05 * width),
            y1 + max(18, int(0.22 * height)),
        ),
    ]
    if wide:
        crop_boxes.extend(
            [
                (x0, y0 + int(0.45 * height), x1, y1 + max(28, int(0.32 * height))),
                (
                    x0 + int(0.10 * width),
                    y0 + int(0.35 * height),
                    x1 - int(0.10 * width),
                    y1 + max(36, int(0.38 * height)),
                ),
            ]
        )
    return _read_boxes(crop_boxes)


def _load_visible_label_cache(
    output_dir: str, profile: Optional[dict] = None
) -> Dict[str, Dict]:
    """Load precomputed structure-label OCR cache when available.

    The cache is intentionally optional: if a run has not generated it yet,
    binder falls back to per-structure visual OCR. When present, however, these
    labels are the highest-priority binding evidence because they come from the
    drawing/label region itself rather than prose text.
    """
    candidates: List[Path] = []
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
        except Exception as exc:
            logger.warning("   可见编号缓存读取失败 %s: %s", path, exc)
            continue
        if isinstance(payload, dict):
            logger.info(
                "   👁 加载结构可见编号缓存: %s (%d structures)", path, len(payload)
            )
            return payload
        logger.warning("   可见编号缓存格式不是 dict，忽略: %s", path)
    return {}


def _visible_labels_for_structure(
    doc,
    struct: Dict,
    visible_label_cache: Optional[Dict[str, Dict]] = None,
    fast_only: bool = True,
) -> List[str]:
    labels: List[str] = []
    cache_item = (visible_label_cache or {}).get(str(struct.get("id") or ""))
    if _visible_cache_item_matches_structure(cache_item, struct):
        return _labels_from_visible_cache_item(cache_item)
    sources = [
        _ocr_visible_label_band_from_page_image(struct),
        _direct_labels_from_structure_image(struct),
    ]
    if not fast_only:
        sources.append(_ocr_visible_label_band(doc, struct))
    for source in sources:
        for label in source:
            if label not in labels:
                labels.append(label)
    return labels


def _normalise_ocr_line_map(
    ocr_line_map: Optional[Dict[int, List[Any]]],
) -> Dict[int, List[Tuple[float, str]]]:
    lines_by_page: Dict[int, List[Tuple[float, str]]] = {}
    for raw_page, raw_lines in (ocr_line_map or {}).items():
        try:
            page_idx = int(raw_page)
        except Exception:
            continue
        if not isinstance(raw_lines, list):
            continue
        normalised: List[Tuple[float, str]] = []
        for item in raw_lines:
            try:
                if isinstance(item, dict):
                    y0 = float(item.get("y0", 0))
                    text = str(item.get("text", "")).strip()
                elif isinstance(item, (list, tuple)) and len(item) >= 2:
                    y0 = float(item[0])
                    text = str(item[1]).strip()
                else:
                    continue
            except Exception:
                continue
            if text:
                normalised.append((y0, text))
        if normalised:
            lines_by_page[page_idx] = sorted(normalised, key=lambda row: row[0])
    return lines_by_page


def _annotate_isotope_label_evidence(
    bindings: List[Dict],
    ocr_line_map: Optional[Dict[int, List[Any]]],
) -> List[Dict]:
    """Reuse page OCR lines to flag isotope and exact visible-label evidence."""
    lines_by_page = _normalise_ocr_line_map(ocr_line_map)
    if not bindings or not lines_by_page:
        return bindings
    annotated: List[Dict] = []
    for binding in bindings:
        item = dict(binding)
        try:
            page_idx = int(item.get("page_no") or 0) - 1
            y0 = float(item.get("struct_y0") or item.get("y0") or 0)
            y1 = float(item.get("struct_y1") or item.get("y1") or y0)
        except Exception:
            annotated.append(item)
            continue
        key = _binding_label_key(item)
        if key:
            exact_label = _nearby_exact_product_label(
                {
                    "page_no": item.get("page_no"),
                    "x0": item.get("struct_x0") or item.get("x0"),
                    "x1": item.get("struct_x1") or item.get("x1"),
                    "y0": y0,
                    "y1": y1,
                    "id": item.get("source_structure_id") or item.get("structure_id"),
                },
                key,
                lines_by_page,
            )
            if exact_label:
                item["nearby_exact_product_label"] = exact_label
                if exact_label != key:
                    item["fail_closed"] = True
                    item["accuracy_status"] = "needs_review"
                    item.setdefault("evidence_reasons", [])
                    item["evidence_reasons"].append(
                        f"nearby visible label is {exact_label}, expected {key}"
                    )
        matches = []
        for line_y, text in lines_by_page.get(page_idx, []):
            if y0 - 24 <= float(line_y) <= y1 + 24 and _CD3_LINE_RE.search(
                str(text or "")
            ):
                matches.append(str(text).strip())
        if matches:
            item["isotope_label_evidence"] = "CD3"
            item["isotope_label_ocr_lines"] = matches[:6]
        annotated.append(item)
    return annotated
