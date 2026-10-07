"""Versioned visible-label observations and exact crop identity."""

from __future__ import annotations

import logging
import re
from typing import (
    Any,
)

from patent_sar_extractor.artifact_io import write_json_atomic

from .binding_geometry import (
    _group_structures_by_row,
    _row_for_structure,
)
from .binding_labels import (
    _base_cpd_num,
    _binding_label_key,
    _cpd_label_key,
    _is_truncated_visible_prefix,
    _nearby_exact_product_label,
    _nearby_ocr_label_kind,
    _normalise_compound_label,
)
from .visible_label_cache import (
    _VISIBLE_LABEL_CACHE_VERSION,
    _filter_visible_label_cache_for_structures,
    _has_original_identity,
    _labels_from_visible_cache_item,
    _load_visible_label_cache,
    _normalise_visible_cache_item,
    _structure_cache_signature,
    _visible_cache_item_matches_structure,
    _visible_label_cache_path,
    _visible_label_candidates_for_structure,
)

logger = logging.getLogger(__name__)

# Preserve the internal import contract without a second implementation.
__all__ = [
    "_VISIBLE_LABEL_CACHE_VERSION",
    "_filter_visible_label_cache_for_structures",
    "_has_original_identity",
    "_labels_from_visible_cache_item",
    "_load_visible_label_cache",
    "_normalise_visible_cache_item",
    "_structure_cache_signature",
    "_visible_cache_item_matches_structure",
    "_visible_label_cache_path",
    "_visible_label_candidates_for_structure",
]

_CD3_LINE_RE = re.compile(r"(?:CD\s*[_₃3]?3?|C\s*D\s*[_₃3]?3)", re.IGNORECASE)


def _refine_visible_label_cache_with_page_ocr(
    processed_structures: list[dict],
    visible_label_cache: dict[str, dict] | None,
    ocr_line_map: dict[int, list[Any]] | None,
    output_dir: str,
    profile: dict | None = None,
) -> dict[str, dict]:
    """Use full-page OCR label rows to restore suffixes lost by tight crops."""
    processed_structures = [
        s for s in processed_structures if _has_original_identity(s)
    ]
    visible_label_cache = _filter_visible_label_cache_for_structures(
        visible_label_cache, processed_structures
    )
    if not visible_label_cache or not ocr_line_map:
        return visible_label_cache or {}
    lines_by_page = _normalise_ocr_line_map(ocr_line_map)
    if not lines_by_page:
        return visible_label_cache
    struct_by_id = {
        str(struct.get("id") or ""): struct for struct in processed_structures
    }
    rows_by_page: dict[int, list[list[dict]]] = {}
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

    refined: dict[str, dict] = {}
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
        candidates: list[dict[str, str]] = []
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
            write_json_atomic(path, refined)
            logger.info(
                "   👁 页面OCR校正可见编号缓存: %d candidates -> %s", changed, path
            )
        except (OSError, TypeError, ValueError) as exc:
            logger.warning("   页面OCR校正可见编号缓存写入失败: %s", exc)
    return refined


def _annotate_bindings_with_visible_labels(
    bindings: list[dict],
    visible_label_cache: dict[str, dict] | None,
) -> list[dict]:
    if not bindings or not visible_label_cache:
        return bindings
    annotated: list[dict] = []
    for binding in bindings:
        item = dict(binding)
        sid = str(item.get("source_structure_id") or item.get("structure_id") or "")
        candidates = _normalise_visible_cache_item((visible_label_cache or {}).get(sid))
        if candidates:
            labels: list[str] = []
            sources: list[str] = []
            label_sources: dict[str, list[str]] = {}
            normalized_candidates: list[dict[str, str]] = []
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


def _normalise_ocr_line_map(
    ocr_line_map: dict[int, list[Any]] | None,
) -> dict[int, list[tuple[float, str]]]:
    lines_by_page: dict[int, list[tuple[float, str]]] = {}
    for raw_page, raw_lines in (ocr_line_map or {}).items():
        try:
            page_idx = int(raw_page)
        except (TypeError, ValueError, OverflowError) as exc:
            logger.debug("Invalid OCR page index was not used: %s", exc)
            continue
        if not isinstance(raw_lines, list):
            continue
        normalised: list[tuple[float, str]] = []
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
            except (TypeError, ValueError, OverflowError) as exc:
                logger.debug("Invalid OCR line coordinate was not used: %s", exc)
                continue
            if text:
                normalised.append((y0, text))
        if normalised:
            lines_by_page[page_idx] = sorted(normalised, key=lambda row: row[0])
    return lines_by_page


def _annotate_isotope_label_evidence(
    bindings: list[dict],
    ocr_line_map: dict[int, list[Any]] | None,
) -> list[dict]:
    """Reuse page OCR lines to flag isotope and exact visible-label evidence."""
    lines_by_page = _normalise_ocr_line_map(ocr_line_map)
    if not bindings or not lines_by_page:
        return bindings
    annotated: list[dict] = []
    for binding in bindings:
        item = dict(binding)
        try:
            page_idx = int(item.get("page_no") or 0) - 1
            y0 = float(item.get("struct_y0") or item.get("y0") or 0)
            y1 = float(item.get("struct_y1") or item.get("y1") or y0)
        except (TypeError, ValueError, OverflowError):
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
