"""Load the original segmented input and one shared page-observation view."""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict

from patent_sar_extractor.artifact_io import write_json_atomic

from .binding_ocr import (
    _extract_binder_page_lines,
    _extract_binder_page_text,
    _get_ocr_line_coords,
)
from .binding_tables import _is_structure_table_context
from .binding_types import BindingObservations

logger = logging.getLogger(__name__)


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
            except Exception:
                page_idx = None
        try:
            page_idx_int = int(page_idx)
        except Exception:
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

    page_ocr_cache_payload: Dict[str, Any] = {}
    if page_ocr_cache_path.is_file():
        try:
            with open(page_ocr_cache_path, "r", encoding="utf-8") as f:
                loaded_cache = json.load(f)
            if isinstance(loaded_cache, dict):
                page_ocr_cache_payload = loaded_cache
                logger.info("   加载页面OCR缓存: %s", page_ocr_cache_path)
        except Exception as exc:
            logger.debug("Page OCR cache load failed %s: %s", page_ocr_cache_path, exc)

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
        for k, v in (profile.get("ocr_text_map", {}) or {}).items()
        if str(k).isdigit() and isinstance(v, str)
    }
    for k, v in (cached_page_texts or {}).items():
        if str(k).isdigit() and isinstance(v, str) and int(k) not in cached_text_map:
            cached_text_map[int(k)] = v
    cached_line_map = {
        int(k): [
            (float(item.get("y0", 0)), str(item.get("text", "")))
            for item in v
            if str(item.get("text", "")).strip()
        ]
        for k, v in (profile_line_map or {}).items()
        if str(k).isdigit() and isinstance(v, list)
    }
    for k, v in (cached_page_lines or {}).items():
        if str(k).isdigit() and isinstance(v, list) and int(k) not in cached_line_map:
            normalised_lines = []
            for item in v:
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
                    normalised_lines.append((y0, text))
            if normalised_lines:
                cached_line_map[int(k)] = sorted(
                    normalised_lines, key=lambda row: row[0]
                )

    pages_text: Dict[int, str] = {}
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
            page = doc[i]
            text = page.get_text("text")
            if not text.strip():
                try:
                    from patent_sar_extractor.core.patent_profiler import (
                        _ocr_page_fallback,
                    )

                    text = _ocr_page_fallback(page)
                except Exception:
                    pass
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
                try:
                    resolved_idx, text = future.result()
                except Exception as exc:
                    logger.debug(
                        "Binder text extraction failed on page %s: %s",
                        page_idx + 1,
                        exc,
                    )
                    continue
                if text.strip():
                    pages_text[resolved_idx] = text

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
        except Exception:
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

        def _checkpoint_page_ocr_lines() -> None:
            page_ocr_cache_payload.setdefault("page_texts", {})
            page_ocr_cache_payload.setdefault("ocr_line_map", {})
            for idx, text in cached_text_map.items():
                page_ocr_cache_payload["page_texts"][str(idx)] = text
            for idx, lines in cached_line_map.items():
                if lines:
                    page_ocr_cache_payload["ocr_line_map"][str(idx)] = [
                        {"y0": round(float(y0), 2), "text": str(text)}
                        for y0, text in lines
                        if str(text).strip()
                    ]
            page_ocr_cache_path.parent.mkdir(parents=True, exist_ok=True)
            write_json_atomic(page_ocr_cache_path, page_ocr_cache_payload)

        if bind_workers <= 1 or len(missing_line_indices) <= 1:
            for idx in missing_line_indices:
                lines = _get_ocr_line_coords(doc[idx]) or []
                if lines:
                    cached_line_map[idx] = lines
                completed_since_checkpoint += 1
                if completed_since_checkpoint >= 10:
                    _checkpoint_page_ocr_lines()

                    completed_since_checkpoint = 0
        else:
            max_workers = min(bind_workers, len(missing_line_indices))
            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                future_map = {
                    pool.submit(_extract_binder_page_lines, pdf_path, idx): idx
                    for idx in missing_line_indices
                }
                for future in as_completed(future_map):
                    idx = future_map[future]
                    try:
                        resolved_idx, lines = future.result()
                    except Exception as exc:
                        logger.debug(
                            "Binder line OCR failed on page %s: %s", idx + 1, exc
                        )

                        continue
                    if lines:
                        cached_line_map[resolved_idx] = lines
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
        except Exception as exc:
            logger.warning("   页面OCR缓存写入失败 %s: %s", page_ocr_cache_path, exc)
    return BindingObservations(
        page_indices,
        pages_text,
        cached_line_map,
        frozenset(authoritative_table_page_indices),
        bind_workers,
    )
