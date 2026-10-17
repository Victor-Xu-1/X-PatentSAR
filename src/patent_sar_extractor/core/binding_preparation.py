"""Load the original segmented input and one shared page-observation view."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .binding_page_source import binding_page_source
from .binding_source_lines import line_locators
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

    profile_line_map = profile.get("ocr_line_map", {}) or {}
    page_ocr_cache_payload, source_lines = binding_page_source(
        doc, pdf_path, page_ocr_cache_path, bind_workers, profile_line_map
    )
    cached_line_map = {
        page: line_locators(lines) for page, lines in source_lines.items() if lines
    }
    pages_text = {
        int(index): text for index, text in page_ocr_cache_payload["page_texts"].items()
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
    return BindingObservations(
        page_indices,
        pages_text,
        cached_line_map,
        frozenset(authoritative_table_page_indices),
        bind_workers,
        source_lines,
    )
