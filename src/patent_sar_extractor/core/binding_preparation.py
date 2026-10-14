"""Load the original segmented input and one shared page-observation view."""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from patent_sar_extractor.artifact_io import write_json_atomic

from .binding_ocr import (
    _extract_binder_page_text,
    _extract_binder_source_lines,
    _get_ocr_line_observations,
)
from .binding_source_lines import line_locators, merged_source_lines, source_line_map
from .binding_tables import _is_structure_table_context
from .binding_types import BindingObservations
from .page_ocr_cache import build_cache_metadata, cache_matches_pdf, page_text

logger = logging.getLogger(__name__)


def _worker_observation(future, page_index, kind):
    try:
        resolved, value = future.result()
    except Exception as exc:
        raise RuntimeError(
            f"Original {kind} observer failed on page {page_index + 1}"
        ) from exc
    if type(resolved) is not int or resolved != page_index:
        raise RuntimeError(f"Original {kind} observer returned a different page")
    if kind == "text":
        if not isinstance(value, str) or len(value) > 100000:
            raise RuntimeError(
                "Original page text observation is malformed or over-bound"
            )
        return value
    try:
        return source_line_map({page_index: value})[page_index]
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            "Original page line observation is malformed or over-bound"
        ) from exc


def load_binding_input(
    output_dir: str,
    structures_path: str | None,
) -> tuple[Path, list[dict[str, Any]], str]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    logger.info(f"📁 输出目录: {out}")

    # ── 1. 加载 Step 6 结构数据 ──────────────────────────────────
    if structures_path is None:
        # 自动搜索: output_dir/../structures/metadata.json 或 output_dir/metadata.json
        candidates = [
            out.parent / "structures" / "metadata.json",
            out / "metadata.json",
        ]
        for c in candidates:
            if c.exists():
                structures_path = str(c)
                break
        if structures_path is None:
            raise FileNotFoundError(
                f"找不到 Step 6 结构数据。请提供 structures_path 参数。"
                f"已搜索: {[str(c) for c in candidates]}"
            )

    logger.info(f"📦 加载结构数据: {structures_path}")
    with open(structures_path, "r", encoding="utf-8") as f:
        step6_metadata = json.load(f)

    structures = step6_metadata.get("structures", [])
    patent_id = step6_metadata.get("patent_number", "unknown")
    logger.info(f"   加载了 {len(structures)} 个结构 (patent={patent_id})")
    return out, structures, patent_id


def prepare_binding_observations(
    doc: Any,
    pdf_path: str,
    profile: dict[str, Any],
    out: Path,
    structures: list[dict[str, Any]],
) -> BindingObservations:
    logger.info(f"   PDF: {pdf_path} ({len(doc)} 页)")

    candidate_pages = sorted(set(profile.get("structure_candidate_pages", []) or []))
    structure_page_indices: set[int] = set()
    for raw_struct in structures:
        page_idx = raw_struct.get("page_idx")
        if page_idx is None:
            page_no = raw_struct.get("page_no", raw_struct.get("page_num", 0))
            try:
                page_idx = int(page_no) - 1
            except (ValueError, TypeError, OverflowError):
                page_idx = None
        try:
            page_idx_int = int(page_idx)
        except (ValueError, TypeError, OverflowError):
            logger.debug("Structure has no valid original page coordinate")
            continue
        if 0 <= page_idx_int < len(doc):
            structure_page_indices.add(page_idx_int)

    if candidate_pages:
        page_indices = sorted(set(candidate_pages) | structure_page_indices)
    else:
        page_indices = list(range(len(doc)))
    if structure_page_indices and candidate_pages:
        logger.info(
            "   结构页文本上下文补充: candidate=%d, structure_pages=%d, merged=%d",
            len(candidate_pages),
            len(structure_page_indices),
            len(page_indices),
        )
    bind_workers = max(1, int(profile.get("bind_workers", 1) or 1))
    page_ocr_cache_path = (
        Path(str(profile.get("ocr_cache_path") or "")).expanduser()
        if profile.get("ocr_cache_path")
        else None
    )
    if page_ocr_cache_path and not page_ocr_cache_path.is_absolute():
        page_ocr_cache_path = out.parent / page_ocr_cache_path
    if not page_ocr_cache_path:
        page_ocr_cache_path = out.parent / "page_classification" / "page_ocr_cache.json"

    page_ocr_cache_payload: dict[str, Any] = {}
    if page_ocr_cache_path.is_file():
        try:
            with open(page_ocr_cache_path, "r", encoding="utf-8") as f:
                loaded_cache = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("Original page OCR cache cannot be read") from exc
        if not cache_matches_pdf(loaded_cache, pdf_path, len(doc)):
            raise ValueError("Page OCR cache does not prove the original PDF identity")
        page_ocr_cache_payload = loaded_cache
        logger.info("   加载页面OCR缓存: %s", page_ocr_cache_path)

    profile_line_map = profile.get("ocr_line_map", {}) or {}
    cached_page_texts = (
        page_ocr_cache_payload.get("page_texts", {})
        if isinstance(page_ocr_cache_payload, dict)
        else {}
    )
    cached_page_lines = (
        page_ocr_cache_payload.get("ocr_line_map", {})
        if isinstance(page_ocr_cache_payload, dict)
        else {}
    )

    cached_text_map = {
        int(k): v
        for k, v in (cached_page_texts or {}).items()
        if str(k).isdigit() and isinstance(v, str)
    }
    for k, v in {
        int(k): v
        for k, v in (profile.get("ocr_text_map", {}) or {}).items()
        if str(k).isdigit() and isinstance(v, str)
    }.items():
        cached_text_map.setdefault(k, v)
    source_lines = merged_source_lines(profile_line_map, cached_page_lines)
    cached_line_map = {
        page: line_locators(lines) for page, lines in source_lines.items() if lines
    }

    pages_text: dict[int, str] = {}
    missing_page_indices = []
    for i in page_indices:
        if i < 0 or i >= len(doc):
            continue
        if i in cached_text_map:
            pages_text[i] = cached_text_map[i]
        else:
            missing_page_indices.append(i)

    if bind_workers <= 1 or len(missing_page_indices) <= 1:
        for i in missing_page_indices:
            text = page_text(doc[i], min_native_chars=0)
            if text.strip():
                pages_text[i] = text
    else:
        max_workers = min(bind_workers, len(missing_page_indices))
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            future_map = {
                pool.submit(_extract_binder_page_text, pdf_path, i): i
                for i in missing_page_indices
            }
            for future in as_completed(future_map):
                page_idx = future_map[future]
                text = _worker_observation(future, page_idx, "text")
                if text.strip():
                    pages_text[page_idx] = text

    if candidate_pages:
        logger.info(f"   使用结构候选页约束: {len(candidate_pages)} 页")

    # Structure tables need OCR line coordinates for the left compound-number
    # column. Older locator outputs stored only flattened text, so fill line
    # coordinates here for table-like pages instead of falling back to prose order.
    contextual_table_page_indices = {
        int(page_idx)
        for page_idx, text in pages_text.items()
        if _is_structure_table_context(text)
    }
    authoritative_table_page_indices: set[int] = set()
    for raw_page_idx in profile.get("authoritative_structure_table_pages", []) or []:
        try:
            page_idx = int(raw_page_idx)
        except (ValueError, TypeError, OverflowError):
            logger.debug(
                "Declared structure table has no valid original page coordinate"
            )
            continue
        if 0 <= page_idx < len(doc):
            authoritative_table_page_indices.add(page_idx)
    table_page_indices = sorted(
        contextual_table_page_indices | authoritative_table_page_indices
    )
    missing_line_indices = [
        idx
        for idx in table_page_indices
        if idx not in cached_line_map and 0 <= idx < len(doc)
    ]
    if missing_line_indices:
        logger.info(
            "   表格页OCR行坐标补扫: %d pages (configured OCR)",
            len(missing_line_indices),
        )
        completed_since_checkpoint = 0
        fresh_source_pages = set()

        def _checkpoint_page_ocr_lines() -> None:
            if not fresh_source_pages:
                return
            if not page_ocr_cache_payload:
                page_ocr_cache_payload["metadata"] = build_cache_metadata(
                    pdf_path, len(doc)
                )
            page_ocr_cache_payload.setdefault("page_texts", {})
            page_ocr_cache_payload.setdefault("ocr_line_map", {})
            for idx in fresh_source_pages:
                lines = source_lines[idx]
                if lines:
                    if not page_ocr_cache_payload["ocr_line_map"].get(str(idx)):
                        page_ocr_cache_payload["ocr_line_map"][str(idx)] = lines
                    if not page_ocr_cache_payload["page_texts"].get(str(idx)):
                        page_ocr_cache_payload["page_texts"][str(idx)] = "\n".join(
                            line["text"] for line in lines
                        )
            page_ocr_cache_path.parent.mkdir(parents=True, exist_ok=True)
            write_json_atomic(page_ocr_cache_path, page_ocr_cache_payload)

        if bind_workers <= 1 or len(missing_line_indices) <= 1:
            for idx in missing_line_indices:
                lines = _get_ocr_line_observations(doc[idx]) or []
                if lines:
                    source_lines[idx] = lines
                    cached_line_map[idx] = line_locators(lines)
                    fresh_source_pages.add(idx)
                completed_since_checkpoint += 1
                if completed_since_checkpoint >= 10:
                    _checkpoint_page_ocr_lines()

                    completed_since_checkpoint = 0
        else:
            max_workers = min(bind_workers, len(missing_line_indices))
            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                future_map = {
                    pool.submit(_extract_binder_source_lines, pdf_path, idx): idx
                    for idx in missing_line_indices
                }
                for future in as_completed(future_map):
                    idx = future_map[future]
                    lines = _worker_observation(future, idx, "line")
                    if lines:
                        source_lines[idx] = lines
                        cached_line_map[idx] = line_locators(lines)
                        fresh_source_pages.add(idx)
                    completed_since_checkpoint += 1
                    if completed_since_checkpoint >= 10:
                        _checkpoint_page_ocr_lines()
                        completed_since_checkpoint = 0
        logger.info(
            "   表格页OCR行坐标可用: %d/%d",
            sum(1 for idx in table_page_indices if idx in cached_line_map),
            len(table_page_indices),
        )
        try:
            _checkpoint_page_ocr_lines()
            logger.info("   更新页面OCR缓存: %s", page_ocr_cache_path)
        except OSError as exc:
            logger.warning("   页面OCR缓存写入失败 %s: %s", page_ocr_cache_path, exc)
    return BindingObservations(
        page_indices,
        pages_text,
        cached_line_map,
        frozenset(authoritative_table_page_indices),
        bind_workers,
        source_lines,
    )
