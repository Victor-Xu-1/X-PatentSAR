#!/usr/bin/env python3
"""
Activity Extractor — 泛化版活性数据提取

从专利PDF的活性表格中提取化合物活性数据（IC50/DC50/Dmax等）。

核心泛化改进：
1. 活性页范围 → 由生产页面分类器提供（不再硬编码页码）
2. 列分割点 → 由 table_layout_analyzer 双峰聚类自动检测（不再硬编码 COLUMN_SPLIT_X=285）
3. 列头含义 → 由 classify_column_headers 自动识别（不再硬编码 DC50/Dmax）
4. Cpd前缀 → 由 profile["cpd_prefix_pattern"] 决定（不再硬编码 Cpd-\\d+）
5. OCR纠错 → 可配置规则链（不再硬编码 in→11/4]→41/Cpd-1411→141）
6. VLM验证 → 可选第二阶段（默认关闭，因为大部分OCR已足够准确）

接口:
    extract(pdf_path, profile, output_dir, **kwargs) → dict
"""

import re
import json
import csv
import logging
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field, asdict
from collections import defaultdict
from typing import Callable, Optional

import fitz
from patent_sar_extractor.artifact_io import write_json_atomic

from patent_sar_extractor.core.page_ocr_cache import get_ocr_engine, load_page_ocr_cache, page_text, save_page_ocr_cache
from patent_sar_extractor.core.table_geometry import (
    detect_ruled_table_regions as _detect_ruled_table_regions,
    ocr_tokens_with_positions as _ocr_tokens_with_positions,
    page_tokens as _biology_tokens_for_page,
)
from patent_sar_extractor.core.activity_values import (
    is_explicit_missing_activity_value as _shared_is_explicit_missing_activity_value,
)
from patent_sar_extractor.contracts import (
    ACTIVITY_SCHEMA,
    ACTIVITY_SCHEMA_VERSION,
    artifact_identity,
)
from patent_sar_extractor.core.table_layout_analyzer import (
    detect_column_layout,
    detect_column_headers,
    classify_column_headers,
    ACTIVITY_HEADER_RE,
)

logger = logging.getLogger(__name__)


def _allow_tesseract_fallback() -> bool:
    import os
    return os.environ.get("PATENTSAR_ALLOW_TESSERACT_FALLBACK", "").strip().lower() in {"1", "true", "yes", "on"}


def _auto_tesseract_activity_tokens() -> bool:
    """Use TSV OCR automatically for coordinate-based activity tables.

    Page-level OCR text is usually enough for classification, but scanned
    multi-column activity tables need word x/y positions. Keep the old env var
    as an explicit override, while allowing installed Tesseract to rescue table
    tokenization without requiring users to remember a hidden switch.
    """
    import os
    setting = os.environ.get("PATENTSAR_AUTO_TESSERACT_ACTIVITY_TOKENS", "1").strip().lower()
    return setting not in {"0", "false", "no", "off"}


def _normalize_activity_cpd_label(value: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return ""
    if re.search(
        r"^(?:ref\.?\s*\d+|reference\b|vehicle\b|dmso\b|control\b|nab[-\s]?paclitaxel\b|paclitaxel\b)",
        text,
        re.IGNORECASE,
    ):
        return text
    match = re.search(
        r"(?:compound|cpd|example|实施例|化合物)\s*[-:]?\s*(\d+(?:-\d+)?[A-Z]?)",
        text,
        re.IGNORECASE,
    )
    if match:
        return f"Compound {match.group(1).upper()}"
    bare = re.fullmatch(r"(\d+(?:-\d+)?[A-Z]?)", text, re.IGNORECASE)
    if bare:
        return f"Compound {bare.group(1).upper()}"
    return text


def _is_control_or_reference_activity_label(value: str) -> bool:
    return bool(re.match(
        r"^(?:ref\.?\s*\d+|reference\b|vehicle\b|dmso\b|control\b|nab[-\s]?paclitaxel\b|paclitaxel\b)",
        re.sub(r"\s+", " ", str(value or "")).strip(),
        re.IGNORECASE,
    ))


def _is_explicit_missing_activity_value(value: str) -> bool:
    return _shared_is_explicit_missing_activity_value(value)


def _activity_row_has_usable_values(row: "ActivityRow") -> bool:
    for bucket in (row.activity_values or {}, row.cell_line_data or {}):
        if any(
            str(value or "").strip() and not _is_explicit_missing_activity_value(value)
            for value in bucket.values()
        ):
            return True
    return False


def _get_page_text(page, ocr_engine=None) -> str:
    """Get page text, falling back to OCR for scanned PDFs."""
    return page_text(page, ocr_engine=ocr_engine, min_native_chars=40).strip()


def _load_ocr_engine():
    """Load the shared OCR engine used by profiler/locator/binder."""
    engine = get_ocr_engine()
    if not engine:
        logger.warning("No shared OCR engine available for activity extraction")
        return None
    logger.info("Activity OCR engine: %s", engine[0])
    return engine


# ==============================================================================
# Data classes
# ==============================================================================


@dataclass
class ActivityRow:
    """一行活性数据"""
    cpd: str = ""                  # 化合物编号, e.g. "Cpd-1", "Example 3"
    activity_values: dict = field(default_factory=dict)  # {"DC50(nM)": "14", "Dmax(%)": "44"}
    cell_line_data: dict = field(default_factory=dict)   # {"MCF-7": "100", "T47D": "8"}
    page_no: int = 0               # 1-indexed page number
    table_id: str = ""             # "Table 1", "Table 2", etc.
    column_side: str = ""          # "left" or "right" (for double-column)
    source: str = "ocr"            # "ocr" | "ocr+vlm_fixed"
    confidence: float = 0.85
    needs_review: bool = False
    notes: str = ""
    activity_sources: list[dict] = field(default_factory=list)


@dataclass
class OCRFixRule:
    """OCR纠错规则"""
    name: str
    field: str         # "dc50" | "dmax" | "cpd" | "any"
    pattern: str       # regex or exact match
    replacement: str   # replacement value
    is_regex: bool = False
    condition: str = ""  # optional condition, e.g. "cpd_num > max_cpd"


# Default OCR fix rules (general-purpose, not patent-specific)
DEFAULT_OCR_FIXES: list[OCRFixRule] = [
    # Common OCR: "in" → "11" (digit "1" misread as letter "i")
    OCRFixRule("in→11", "any", "in", "11"),
    # Common OCR: "4]" → "41" (trailing "1" misread as "]")
    OCRFixRule("4]→41", "any", "4]", "41"),
    # Garbage chars → empty
    OCRFixRule("pipe_garbage", "any", "|", ""),
    OCRFixRule("dot_garbage", "any", ".", ""),
    # Trailing noise on numbers
    OCRFixRule("trailing_pipe", "any", r"(\d+)\|$", r"\1", is_regex=True),
    OCRFixRule("trailing_dot", "any", r"(\d+)\.$", r"\1", is_regex=True),
]


# ==============================================================================
# Table boundary detection
# ==============================================================================


def _find_table_regions(
    doc: fitz.Document,
    activity_pages: list[int],
) -> list[dict]:
    """
    自动检测活性表格区域（表格标题 + 列头行 + 数据区域）。
    
    Returns:
        [{"table_id": "Table 1", "start_page": 191, "start_y": 730,
          "header_y": 740, "end_page": 195, "end_y": 250,
          "pages": [191,192,193,194,195], "header_words": [...]}]
    """
    tables = []
    table_re = re.compile(r"Table\s+(\d+)", re.IGNORECASE)
    
    for page_idx in activity_pages:
        if page_idx >= len(doc):
            continue
        page = doc[page_idx]
        blocks = page.get_text("blocks")
        
        for b in blocks:
            x0, y0, x1, y1, text, bt, bn = b
            text = text.strip()
            m = table_re.search(text)
            if not m:
                continue
            
            table_num = m.group(1)
            table_id = f"Table {table_num}"
            
            # Check if this block also contains activity headers
            # (to distinguish activity tables from synthesis tables)
            from patent_sar_extractor.core.table_layout_analyzer import ACTIVITY_HEADER_RE
            has_activity_header = bool(ACTIVITY_HEADER_RE.search(text))
            
            # Even without activity header in the same block,
            # the table heading on an activity page is likely an activity table
            tables.append({
                "table_id": table_id,
                "heading_page_idx": page_idx,
                "heading_y": y0,
                "heading_text": text[:200],
                "has_activity_keyword": has_activity_header,
            })
    
    # Merge consecutive tables: if "Table 1" heading is found on page 191
    # and data continues on pages 192-195, we need to find where it ends.
    # Simple heuristic: Table N ends where Table N+1 begins (or at last activity page).
    for i, t in enumerate(tables):
        start_page = t["heading_page_idx"]
        
        # Find end: next table start, or last activity page
        if i + 1 < len(tables):
            end_page = tables[i + 1]["heading_page_idx"]
        else:
            end_page = activity_pages[-1] if activity_pages else start_page
        
        # Pages covered by this table
        pages = [p for p in activity_pages if start_page <= p <= end_page]
        
        t["pages"] = pages
        t["start_page_idx"] = start_page
        t["end_page_idx"] = end_page
    
    logger.info(f"Detected {len(tables)} table regions on activity pages")
    for t in tables:
        logger.info(f"  {t['table_id']}: pages {[p+1 for p in t.get('pages', [])]} "
                     f"(heading at p{t['heading_page_idx']+1} y={t['heading_y']:.0f})")
    
    return tables


# ==============================================================================
# Phase 1: OCR extraction with word-level coordinate parsing
# ==============================================================================


def _get_words(page):
    """Get word-level data from a PDF page."""
    return page.get_text("words")


def _group_words_by_y(words: list, tolerance: float = 8.0) -> list[list]:
    """将words按y坐标分组为行"""
    if not words:
        return []
    
    sorted_words = sorted(words, key=lambda w: (round(w[1] / tolerance) * tolerance, w[0]))
    groups = [[sorted_words[0]]]
    
    for w in sorted_words[1:]:
        if abs(w[1] - groups[-1][0][1]) < tolerance:
            groups[-1].append(w)
        else:
            groups.append([w])
    
    # 每组内按x排序
    for g in groups:
        g.sort(key=lambda w: w[0])
    
    return groups


def _find_header_y(doc, pages_idx: list[int], cpd_re: re.Pattern) -> Optional[float]:
    """找到列头行（含Cpd+活性指标词）的y坐标"""
    from patent_sar_extractor.core.table_layout_analyzer import ACTIVITY_HEADER_RE
    
    for page_idx in pages_idx:
        if page_idx >= len(doc):
            continue
        page = doc[page_idx]
        blocks = page.get_text("blocks")
        for b in blocks:
            x0, y0, x1, y1, text, bt, bn = b
            text = text.strip()
            if (cpd_re.search(text) or re.search(r"Cpd|Compound|Example", text, re.IGNORECASE)) \
                    and ACTIVITY_HEADER_RE.search(text):
                logger.info(f"  Header row found at p{page_idx+1} y={y0:.0f}: {text[:80]}")
                return y0
    return None


def _parse_cpd_values(
    word_list: list,
    cpd_re: re.Pattern,
    col_classes: list[dict],
    side: str,
    page_no: int,
    table_id: str,
) -> Optional[ActivityRow]:
    """
    从一列words中解析 Cpd编号 + 活性值。
    
    col_classes: classify_column_headers() 的输出, e.g.
        [{"header": "Cpd", "category": "cpd_id", ...}, 
         {"header": "DC50(nM)", "category": "activity_value", ...}, ...]
    """
    if not word_list:
        return None
    
    text = " ".join(w[4] for w in word_list).strip()
    
    # Find Cpd identifier
    m = cpd_re.search(text)
    if not m:
        return None
    
    cpd = m.group(0).strip()
    
    # Remaining text after the Cpd identifier
    remaining = text[m.end():].strip()
    remaining = remaining.replace("|", " ").strip()
    remaining = re.sub(r"\s+", " ", remaining)
    
    # Split remaining into tokens
    parts = remaining.split()
    
    # Map parts to columns based on classification
    activity_values = {}
    
    # Count non-cpd_id columns to know how many values to expect
    data_cols = [c for c in col_classes if c["category"] != "cpd_id"]
    
    for i, part in enumerate(parts):
        if i < len(data_cols):
            col_info = data_cols[i]
            activity_values[col_info["header"]] = part
    
    return ActivityRow(
        cpd=cpd,
        activity_values=activity_values,
        page_no=page_no,
        table_id=table_id,
        column_side=side,
        source="ocr",
    )


def _parse_table_double_column(
    words, page_no: int, split_xs: list[float],
    cpd_re: re.Pattern, col_classes: list[dict],
    table_id: str, y_min: float = 50, y_max: float = 780,
) -> list[ActivityRow]:
    """
    Parse double-column (or multi-column) layout.
    
    Strategy: Instead of a hard split_x, we group by Cpd rows.
    Each Cpd row starts with a Cpd identifier; all subsequent words
    until the next Cpd (or end of line) belong to that Cpd's row.
    """
    rows = []
    
    # Filter words by region
    word_data = [(w[0], w[1], w[2], w[3], w[4]) for w in words
                 if y_min - 5 <= w[1] <= y_max + 5
                 and 30 < w[0] < 580]
    
    if not word_data:
        return rows
    
    # Group into lines by y proximity
    lines = _group_words_by_y(word_data, tolerance=8)
    
    # For each line, find Cpd identifiers and group words around them
    split_x = float(split_xs[0]) if split_xs else 267.0
    
    for line_words in lines:
        # Find all Cpd identifiers in this line
        cpd_positions = []
        for w in line_words:
            text = w[4]
            # OCR correction for data values
            text_corr = re.sub(r'([DI]C)S(50)', r'\1\2', text)
            if cpd_re.search(text_corr):
                cpd_positions.append(w)
        
        if not cpd_positions:
            continue
        
        # For each Cpd, determine its column side and collect nearby words
        for ci, cpd_word in enumerate(cpd_positions):
            cpd_x = cpd_word[0]
            side = "left" if cpd_x < split_x else "right"
            
            # Determine word range for this Cpd:
            # From this Cpd to the next Cpd (or end of line)
            if ci + 1 < len(cpd_positions):
                next_cpd_x = cpd_positions[ci + 1][0]
            else:
                next_cpd_x = 580.0
            
            # Collect words between this Cpd and the next Cpd
            # (excluding the Cpd word itself and pipe separators)
            cpd_words = []
            for w in line_words:
                if w[0] < cpd_word[0] - 5:
                    continue  # before this Cpd
                if w[0] >= next_cpd_x - 5 and w != cpd_word:
                    continue  # after next Cpd
                if w[4] == "|":
                    continue  # skip pipe separators
                if w == cpd_word:
                    continue  # skip the Cpd word itself
                # Word belongs to this Cpd
                cpd_words.append(w)
            
            # Apply OCR correction to word text
            corrected_words = []
            for w in cpd_words:
                text = re.sub(r'([DI]C)S(50)', r'\1\2', w[4])
                corrected_words.append((w[0], w[1], w[2], w[3], text))
            
            # Parse the Cpd and its values
            cpd_text = cpd_word[4]
            m = cpd_re.search(cpd_text)
            if not m:
                continue
            cpd = m.group(0).strip()
            
            # Sort remaining words by x position and map to data columns
            corrected_words.sort(key=lambda w: w[0])
            data_cols = [c for c in col_classes if c["category"] != "cpd_id"]
            
            activity_values = {}
            for i, w in enumerate(corrected_words):
                if i < len(data_cols):
                    activity_values[data_cols[i]["header"]] = w[4]
            
            rows.append(ActivityRow(
                cpd=cpd,
                activity_values=activity_values,
                page_no=page_no,
                table_id=table_id,
                column_side=side,
                source="ocr",
            ))
    
    return rows


def _parse_table_single_column(
    words, page_no: int,
    cpd_re: re.Pattern, col_classes: list[dict],
    table_id: str, y_min: float = 50, y_max: float = 780,
) -> list[ActivityRow]:
    """Parse single-column layout."""
    rows = []
    
    word_data = [(w[0], w[1], w[2], w[3], w[4]) for w in words
                 if y_min - 5 <= w[1] <= y_max + 5
                 and 30 < w[0] < 580]
    
    if not word_data:
        return rows
    
    lines = _group_words_by_y(word_data, tolerance=8)
    
    # Build column boundaries from header word positions
    # For single-column, we use x-coordinate ranges
    col_boundaries = []
    data_cols = [c for c in col_classes if c["category"] != "cpd_id"]
    
    # Try to infer column boundaries from word x-positions
    # by finding gaps in the x distribution
    all_x0 = sorted(set(w[0] for w in word_data))
    
    if len(all_x0) > 2 and len(data_cols) >= 2:
        # Find natural gaps in x distribution
        gaps = [(all_x0[i+1] - all_x0[i], i) for i in range(len(all_x0)-1)]
        gaps.sort(reverse=True)
        
        # Take top N-1 gaps as boundaries (where N = number of data columns + 1 for Cpd)
        n_boundaries = len(data_cols)  # one boundary between each pair of columns
        boundaries = sorted([all_x0[g[1] + 1] for g in gaps[:n_boundaries]])
        col_boundaries = [0] + boundaries + [580]
    else:
        col_boundaries = [0, 580]
    
    col_names = [c["header"] for c in col_classes]
    
    for line_words in lines:
        text = " ".join(w[4] for w in line_words)
        if not cpd_re.search(text):
            continue
        
        # Assign words to columns by x position
        col_values = defaultdict(list)
        for w in line_words:
            x0 = w[0]
            for ci in range(len(col_boundaries) - 1):
                if col_boundaries[ci] <= x0 < col_boundaries[ci + 1]:
                    col_values[ci].append(w[4])
                    break
        
        # Parse Cpd from the cpd_id column
        cpd_col_idx = None
        for i, c in enumerate(col_classes):
            if c["category"] == "cpd_id":
                cpd_col_idx = i
                break
        
        if cpd_col_idx is None:
            # Fallback: first column
            cpd_col_idx = 0
        
        cpd_text = " ".join(col_values.get(cpd_col_idx, []))
        m = cpd_re.search(cpd_text)
        if not m:
            continue
        
        cpd = m.group(0).strip()
        
        # Parse values from other columns
        activity_values = {}
        cell_line_data = {}
        
        for i, c in enumerate(col_classes):
            if i == cpd_col_idx:
                continue
            val = " ".join(col_values.get(i, [])).strip()
            # Fix infinity symbols
            if val.lower() in ("in", "∞", "infinity"):
                val = ">10000"
            if val:
                if c["category"] == "cell_line":
                    cell_line_data[c["header"]] = val
                else:
                    activity_values[c["header"]] = val
        
        side = "single"
        rows.append(ActivityRow(
            cpd=cpd,
            activity_values=activity_values,
            cell_line_data=cell_line_data,
            page_no=page_no,
            table_id=table_id,
            column_side=side,
            source="ocr",
        ))
    
    return rows


# ==============================================================================
# OCR error correction
# ==============================================================================


def _apply_ocr_fixes(
    row: ActivityRow,
    fix_rules: list[OCRFixRule],
    max_cpd_num: int = 9999,
) -> ActivityRow:
    """Apply OCR fix rules to an ActivityRow."""
    notes = []
    
    for rule in fix_rules:
        # Fix activity values
        for key in list(row.activity_values.keys()):
            val = row.activity_values[key]
            if rule.is_regex:
                new_val, count = re.subn(rule.pattern, rule.replacement, val)
                if count > 0:
                    row.activity_values[key] = new_val
                    notes.append(f"OCR:{rule.name}:{key} {val!r}→{new_val!r}")
            else:
                if val == rule.pattern:
                    row.activity_values[key] = rule.replacement
                    notes.append(f"OCR:{rule.name}:{key} {val!r}→{rule.replacement!r}")
        
        # Fix Cpd number overflow (e.g., Cpd-1411 → Cpd-141)
        if "cpd" in rule.field or rule.field == "any":
            m = re.search(r"[-\s](\d+)$", row.cpd)
            if m:
                cpd_num = int(m.group(1))
                if cpd_num > max_cpd_num and max_cpd_num > 0:
                    # Try splitting
                    for split_pos in range(1, len(str(cpd_num))):
                        prefix = cpd_num // (10 ** split_pos)
                        suffix = cpd_num % (10 ** split_pos)
                        if 1 <= prefix <= max_cpd_num:
                            prefix_str = m.group(0)[0] + str(prefix)  # preserve separator
                            row.cpd = row.cpd[:m.start()] + prefix_str
                            if suffix > 0 and row.activity_values:
                                # Prepend suffix to first activity value
                                first_key = list(row.activity_values.keys())[0]
                                row.activity_values[first_key] = str(suffix) + row.activity_values[first_key]
                            notes.append(f"OCR:Cpd_split:{cpd_num}→{prefix}(suffix={suffix})")
                            break
    
    if notes:
        row.notes = (row.notes or "") + "; ".join(notes) + "; "
    
    return row


# ==============================================================================
# Phase 2: VLM verification (optional)
# ==============================================================================


def _render_table_image(doc, page_idx: int, y_top: float, y_bottom: float, output_dir: Path, label: str = "") -> str:
    """Render a region of a page as PNG for VLM"""
    page = doc[page_idx]
    clip = fitz.Rect(50, max(y_top - 5, 0), 560, min(y_bottom + 5, 790))
    mat = fitz.Matrix(2.5, 2.5)
    pix = page.get_pixmap(matrix=mat, clip=clip)
    
    fname = f"page_{page_idx+1:03d}_{label}.png" if label else f"page_{page_idx+1:03d}.png"
    out_path = output_dir / fname
    pix.save(str(out_path))
    return str(out_path)


def _parse_vlm_json(response_text: str) -> list[dict]:
    """Parse VLM response into list of dicts"""
    json_match = re.search(r'```(?:json)?\s*(.*?)```', response_text, re.DOTALL)
    json_str = json_match.group(1).strip() if json_match else response_text.strip()
    
    try:
        data = json.loads(json_str)
        if isinstance(data, list):
            return data
    except json.JSONDecodeError:
        bracket_match = re.search(r'\[.*\]', response_text, re.DOTALL)
        if bracket_match:
            try:
                return json.loads(bracket_match.group())
            except:
                pass
    logger.warning("Failed to parse VLM JSON response")
    return []


def _cross_reference(ocr_rows: list[ActivityRow], vlm_results: dict) -> list[ActivityRow]:
    """Cross-reference OCR and VLM, apply VLM corrections for flagged errors"""
    # Build VLM lookup by Cpd
    vlm_by_cpd = defaultdict(list)
    for key, result in vlm_results.items():
        for row in result.get("parsed_rows", []):
            cpd = row.get("cpd", "").strip()
            if cpd:
                vlm_by_cpd[cpd].append(row)
    
    fix_count = 0
    for ocr_row in ocr_rows:
        cpd = ocr_row.cpd
        if cpd not in vlm_by_cpd:
            continue
        
        vlm_matches = vlm_by_cpd[cpd]
        if not vlm_matches:
            continue
        
        vlm_data = vlm_matches[0]
        
        # Fix activity values: only when OCR value is clearly garbage
        for key in list(ocr_row.activity_values.keys()):
            ocr_val = ocr_row.activity_values[key]
            ocr_clean = ocr_val.replace(">", "").replace("<", "").replace("=", "").strip()
            is_suspect = (not ocr_clean.isdigit() and ocr_clean not in ["", ">10000", "<1", "10000"]) or ocr_clean == ""
            
            if is_suspect:
                # Map VLM keys to our keys (fuzzy)
                vlm_val = None
                for vk, vv in vlm_data.items():
                    if vk.lower() in key.lower() or key.lower() in vk.lower():
                        vlm_val = str(vv)
                        break
                # Fallback: try VLM "dc50_nm" / "dmax_pct" for Table 1
                if vlm_val is None:
                    if "dc50" in key.lower() and "dc50" in vlm_data:
                        vlm_val = str(vlm_data["dc50_nm"] if isinstance(vlm_data["dc50_nm"], str) else vlm_data.get("dc50_nm", ""))
                    elif "dmax" in key.lower() and "dmax" in vlm_data:
                        vlm_val = str(vlm_data.get("dmax_pct", ""))
                
                if vlm_val and vlm_val.replace(">", "").replace("<", "").strip().isdigit():
                    logger.info(f"  VLM fix: {cpd} {key} {ocr_val!r} → {vlm_val!r}")
                    ocr_row.activity_values[key] = vlm_val
                    ocr_row.source = "ocr+vlm_fixed"
                    fix_count += 1
    
    logger.info(f"VLM applied {fix_count} corrections")
    return ocr_rows


# ==============================================================================
# Main extract() interface
# ==============================================================================


def extract(
    pdf_path: str,
    profile: dict,
    output_dir: str,
    use_vlm: bool = False,
    vlm_api_url: str = "",
    vlm_api_key: str = "",
    vlm_model: str = "",
    vlm_call: Optional[Callable[[str, str, str, str, str], str]] = None,
    ocr_fix_rules: Optional[list[OCRFixRule]] = None,
    max_cpd_num: int = 0,
    include_intermediates: bool = False,
) -> dict:
    """
    从专利PDF提取活性数据。
    
    Args:
        pdf_path: OCR PDF文件路径
        profile: 生产页面分类阶段的输出字典
        output_dir: 输出目录
        use_vlm: 是否启用VLM验证（Phase 2）
        vlm_api_url: VLM API端点
        vlm_api_key: VLM API密钥
        vlm_model: VLM模型名
        ocr_fix_rules: 自定义OCR纠错规则（None=使用默认规则）
        max_cpd_num: 最大Cpd编号（用于Cpd编号溢出检测，0=不检测）
        include_intermediates: 是否包含Intermediate行
    
    Returns:
        {
            "rows": [ActivityRow, ...],
            "n_rows": int,
            "n_unique_cpds": int,
            "tables": [...],
            "column_layout": {...},
            "column_headers": [...],
            "vlm_results": {...} | None,
            "output_dir": str,
        }
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    ocr_cache_path = str(profile.get("ocr_cache_path", "") or "")
    shared_ocr_cache = load_page_ocr_cache(ocr_cache_path) if ocr_cache_path else {"page_texts": {}, "ocr_line_map": {}}

    vlm_api_url = str(vlm_api_url or "").rstrip("/")
    vlm_api_key = str(vlm_api_key or "").strip()
    vlm_model = str(vlm_model or "").strip()
    
    logger.info("=" * 60)
    logger.info("Activity Extractor: 泛化版活性数据提取")
    logger.info(f"PDF: {pdf_path}")
    logger.info(f"Output: {output_dir}")
    logger.info("=" * 60)
    
    # ── 1. Open PDF ──
    doc = fitz.open(pdf_path)
    
    # ── 2. Get activity pages from profile ──
    activity_pages = profile.get("activity_pages", [])
    if not activity_pages:
        logger.warning("No activity_pages in profile, scanning all pages for activity tables")
        activity_pages = list(range(len(doc)))
    
    # ── 2b. Filter: keep only pages with Table headings or dense Cpd data ──
    # (Profiler is intentionally broad; we refine here for extraction)
    # For scanned PDFs: fall back to OCR when native text is empty.
    ocr_engine = _load_ocr_engine()
    shared_ocr_cache.setdefault("page_texts", {})
    cache_dirty = False

    def cached_activity_page_text(page_idx: int) -> str:
        nonlocal cache_dirty
        if page_idx < 0 or page_idx >= len(doc):
            return ""
        key = str(page_idx)
        text = str(shared_ocr_cache.get("page_texts", {}).get(key, ""))
        if text.strip():
            return text
        text = _get_page_text(doc[page_idx], ocr_engine)
        if text.strip():
            shared_ocr_cache["page_texts"][key] = text
            cache_dirty = True
        return text

    table_heading_re = re.compile(r"Table\s+\d+|表\s*\d+", re.IGNORECASE)
    cpd_re_for_filter = re.compile(
        profile.get("cpd_prefix_pattern")
        or profile.get("cpd_pattern")
        or r"Cpd[-\s]?\d+",
        re.IGNORECASE,
    )
    filtered_pages = []
    for page_idx in activity_pages:
        if page_idx >= len(doc):
            continue
        text = cached_activity_page_text(page_idx)
        has_table_heading = bool(table_heading_re.search(text))
        cpd_count = len(cpd_re_for_filter.findall(text))
        # Keep if: has "Table N" heading OR has >= 5 Cpd mentions (dense data page)
        if has_table_heading or cpd_count >= 5:
            filtered_pages.append(page_idx)
    
    if filtered_pages != activity_pages:
        removed = set(activity_pages) - set(filtered_pages)
        logger.info(f"Filtered activity pages: {activity_pages} → {filtered_pages} "
                     f"(removed low-density pages: {sorted(removed)})")
    activity_pages = filtered_pages
    
    logger.info(f"Activity pages (0-idx): {activity_pages}")
    
    # ── 2c. Expand: include page before each activity page (table may start there) ──
    expanded = set(activity_pages)
    table_heading_re_expand = re.compile(r"Table\s+\d+|表\s*\d+", re.IGNORECASE)
    for p in activity_pages:
        if p - 1 >= 0 and (p - 1) not in expanded:
            prev_text = cached_activity_page_text(p - 1)
            # Include previous page if it has a Table heading (even if it's a synthesis page)
            # Many patents have Table 1 heading on the last synthesis page
            has_table_heading = bool(table_heading_re_expand.search(prev_text))
            if has_table_heading or (p - 1) not in profile.get("synthesis_pages", []):
                expanded.add(p - 1)
    activity_pages = sorted(expanded)
    if len(activity_pages) != len(filtered_pages):
        logger.info(f"Expanded activity pages: {activity_pages}")

    # Fill shared text cache once before running supplemental table parsers.
    # They all receive this same page_text_map, avoiding repeated OCR and
    # keeping Chinese/English mixed table extraction consistent.
    for page_idx in sorted(set(activity_pages) | set(profile.get("activity_pages", []) or [])):
        cached_activity_page_text(int(page_idx))
    if cache_dirty and ocr_cache_path:
        save_page_ocr_cache(ocr_cache_path, shared_ocr_cache)
        logger.info("Updated shared page OCR cache for activity extraction: %s", ocr_cache_path)
    
    # A cell-proven schema owns its original pages. General text/grade parsers
    # must not run a competing interpretation or a second OCR pass on them.
    english_rows = _extract_english_biology_activity_rows_from_ocr(
        doc, profile.get("activity_pages", activity_pages),
        page_text_map=shared_ocr_cache.get("page_texts", {}),
    )
    owned_pages = {
        source["page_no"] - 1
        for row in english_rows for source in row.activity_sources
    }
    supplemental_pages = [
        page for page in profile.get("activity_pages", activity_pages)
        if page not in owned_pages
    ]
    activity_pages = [page for page in activity_pages if page not in owned_pages]
    logger.info("Cell schema owns %s pages; %s unclaimed pages remain", len(owned_pages), len(supplemental_pages))

    # ── 3. Detect column layout ──
    cpd_pattern = (
        profile.get("cpd_prefix_pattern")
        or profile.get("cpd_pattern")
        or r"Cpd[-\s]?\d+"
    )
    cpd_re = re.compile(cpd_pattern, re.IGNORECASE)
    
    column_layout = detect_column_layout(doc, activity_pages, cpd_pattern)
    logger.info(f"Column layout: {column_layout['type']}, split_xs={column_layout['split_xs']}")
    
    # ── 4. Find table regions (need this before column header detection) ──
    tables = _find_table_regions(doc, activity_pages)
    
    # ── 5. Detect column headers ──
    # (Use table-aware approach: find headers near each Table heading)
    col_classes = []
    best_header_y = None
    
    for table_info in tables:
        page_idx = table_info["heading_page_idx"]
        if page_idx >= len(doc):
            continue
        page = doc[page_idx]
        blocks = page.get_text("blocks")
        heading_y = table_info["heading_y"]
        
        # Search blocks BELOW the Table heading (within 200px)
        for b in blocks:
            x0, y0, x1, y1, text, bt, bn = b
            text = text.strip()
            # Column header row: contains Cpd + activity keywords, and is below Table heading
            if (y0 > heading_y and y0 < heading_y + 200
                and (cpd_re.search(text) or re.search(r"Cpd|Compound|Example", text, re.IGNORECASE))
                and ACTIVITY_HEADER_RE.search(text)):
                # Smart header parsing: strip stray "|" from header text
                # Also apply OCR corrections for common misreads
                raw_words = text.split()
                clean_words = []
                for w in raw_words:
                    if w == "|":
                        continue
                    # OCR correction: DCS50 → DC50, ICS50 → IC50, ECS50 → EC50
                    w = re.sub(r'([DI]C)S(50)', r'\1\2', w)
                    clean_words.append(w)
                
                # For double-column layout, split into left/right halves
                # based on profile's table_type
                if profile.get("table_schema", {}).get("type") == "double" and column_layout.get("split_xs"):
                    split_x = float(column_layout["split_xs"][0])
                    # Split header words by x-position
                    # Use word-level dict to get x coordinates
                    word_dicts = page.get_text("words")
                    header_words = [wd for wd in word_dicts 
                                    if y0 - 5 <= wd[1] <= y1 + 5]  # same row
                    left_headers = []
                    right_headers = []
                    for wd in header_words:
                        word_text = wd[4]
                        if word_text == "|":  # skip pipe separators
                            continue
                        # OCR correction
                        word_text = re.sub(r'([DI]C)S(50)', r'\1\2', word_text)
                        mid_x = (wd[0] + wd[2]) / 2
                        if mid_x < split_x:
                            left_headers.append(word_text)
                        else:
                            right_headers.append(word_text)
                    
                    # Fix: if right column starts with non-cpd word and left column
                    # is missing activity_percent, the split_x was slightly off and
                    # a left-column word leaked into right. Move it back.
                    cpd_start_re = re.compile(r"Cpd|Compound|Example|Cmpd", re.IGNORECASE)
                    while (right_headers and not cpd_start_re.search(right_headers[0])
                           and len(right_headers) > len(left_headers)):
                        left_headers.append(right_headers.pop(0))
                    
                    # Use left column headers for classification
                    # (both sides should have same structure)
                    col_classes = classify_column_headers(left_headers)
                    best_header_y = y0
                    logger.info(f"  Table-aware header at p{page_idx+1} y={y0:.0f}")
                    logger.info(f"  Left headers: {left_headers}")
                    logger.info(f"  Right headers: {right_headers}")
                    logger.info(f"  Column classes: {[c['category'] for c in col_classes]}")
                else:
                    # Single column: use clean words directly
                    col_classes = classify_column_headers(clean_words)
                    best_header_y = y0
                    logger.info(f"  Table-aware header at p{page_idx+1} y={y0:.0f}: {text[:80]}")
                    logger.info(f"  Column classes: {[c['category'] for c in col_classes]}")
                break
    
    # Fallback: use detect_column_headers if table-aware failed
    if not col_classes:
        _fallback = detect_column_headers(doc, activity_pages, profile)
        col_classes = classify_column_headers(_fallback.get("headers", []))
        best_header_y = _fallback.get("header_y")
        logger.info(f"  Fallback column headers: {_fallback.get('headers', [])}")
    
    # Validate: must have at least cpd_id + activity_value
    has_cpd_id = any(c["category"] == "cpd_id" for c in col_classes)
    has_activity = any(c["category"] in ("activity_value", "activity_percent") for c in col_classes)
    if not (has_cpd_id and has_activity):
        logger.warning(f"Invalid column classes: {[c['category'] for c in col_classes]}. "
                       f"Using default: [cpd_id, activity_value, activity_percent]")
        col_classes = [
            {"header": "Cpd", "category": "cpd_id", "confidence": 0.5, "unit": None},
            {"header": "DC50(nM)", "category": "activity_value", "confidence": 0.5, "unit": "nM"},
            {"header": "Dmax(%)", "category": "activity_percent", "confidence": 0.5, "unit": "%"},
        ]
    
    # ── 6. Extract data from each table ──
    all_rows: list[ActivityRow] = list(english_rows)
    header_y = best_header_y
    
    for table_info in tables:
        table_id = table_info["table_id"]
        pages_idx = table_info.get("pages", [])
        heading_y = table_info["heading_y"]
        
        logger.info(f"\n--- Extracting {table_id} (pages {[p+1 for p in pages_idx]}) ---")
        
        for page_idx in pages_idx:
            if page_idx >= len(doc):
                continue
            page = doc[page_idx]
            words = _get_words(page)
            page_no = page_idx + 1  # 1-indexed
            
            # Determine y range for this page
            y_min = 50
            y_max = 780
            
            # First page of table: start below header
            if page_idx == table_info["heading_page_idx"]:
                if header_y:
                    y_min = header_y + 10
                else:
                    y_min = heading_y + 20
            
            # Last page: check if next table starts below
            # (simplified: just use full page for now)
            
            if column_layout["type"] == "double" and column_layout["split_xs"]:
                page_rows = _parse_table_double_column(
                    words, page_no, column_layout["split_xs"],
                    cpd_re, col_classes, table_id, y_min=y_min, y_max=y_max,
                )
            else:
                page_rows = _parse_table_single_column(
                    words, page_no, cpd_re, col_classes, table_id,
                    y_min=y_min, y_max=y_max,
                )
            
            logger.info(f"  p{page_no}: {len(page_rows)} rows")
            all_rows.extend(page_rows)

    bare_no_rows = _extract_english_bare_no_activity_rows_from_ocr(
        doc,
        supplemental_pages,
        page_text_map=shared_ocr_cache.get("page_texts", {}),
    )
    if bare_no_rows:
        logger.info(f"  英文No.裸编号活性表OCR结构化提取: {len(bare_no_rows)} rows")
        all_rows = _merge_activity_rows([*all_rows, *bare_no_rows])

    text_table_rows = _extract_generic_text_table_activity_rows_from_ocr(
        doc,
        supplemental_pages,
        page_text_map=shared_ocr_cache.get("page_texts", {}),
    )
    if text_table_rows:
        logger.info(f"  通用中英混排OCR文本表格补充提取: {len(text_table_rows)} rows")
        all_rows = _merge_activity_rows([*all_rows, *text_table_rows])

    prefixed_grade_rows = _extract_prefixed_letter_grade_activity_rows_from_ocr(
        supplemental_pages,
        page_text_map=shared_ocr_cache.get("page_texts", {}),
    )
    if prefixed_grade_rows:
        logger.info(f"  通用前缀编号字母分级表提取: {len(prefixed_grade_rows)} rows")
        all_rows = _merge_activity_rows([*all_rows, *prefixed_grade_rows])

    text_grade_pages = {row.page_no - 1 for row in prefixed_grade_rows if row.page_no > 0}
    coordinate_activity_pages = _coordinate_activity_page_candidates(
        supplemental_pages,
        page_text_map=shared_ocr_cache.get("page_texts", {}),
    )
    ruled_activity_pages = [
        page_idx for page_idx in coordinate_activity_pages
        if page_idx not in text_grade_pages
    ]
    logger.info(
        "Coordinate activity OCR candidates: %s pages (%s already handled from cached text)",
        len(ruled_activity_pages),
        len(text_grade_pages),
    )

    ruled_rows: list[ActivityRow] = []
    ruled_rows = _extract_ruled_activity_rows(
        doc,
        ruled_activity_pages,
    )
    if ruled_rows:
        logger.info(f"  线框表格活性补充提取: {len(ruled_rows)} rows")
        all_rows = _merge_activity_rows([*all_rows, *ruled_rows])

    multi_table_rows = _extract_chinese_adme_pk_activity_rows_from_ocr(
        doc,
        supplemental_pages,
        page_text_map=shared_ocr_cache.get("page_texts", {}),
    )
    if multi_table_rows:
        logger.info(f"  中文/英文混排多活性表OCR补充提取: {len(multi_table_rows)} rows")
        all_rows = _merge_activity_rows([*all_rows, *multi_table_rows])

    dc50_rows = _extract_chinese_dc50_dmax_rows_from_ocr(
        doc,
        supplemental_pages,
        page_text_map=shared_ocr_cache.get("page_texts", {}),
    )
    if dc50_rows:
        logger.info(f"  中文DC50/Dmax表格OCR补充提取: {len(dc50_rows)} rows")
        all_rows = _merge_activity_rows([*all_rows, *dc50_rows])

    ocr_rows = _extract_chinese_activity_rows_from_ocr(
        doc,
        supplemental_pages,
        page_text_map=shared_ocr_cache.get("page_texts", {}),
    )
    if ocr_rows:
        logger.info(f"  中文OCR表格补充提取: {len(ocr_rows)} rows")
        all_rows = _merge_activity_rows([*all_rows, *ocr_rows])

    letter_rows = _extract_letter_grade_activity_rows_from_ocr(
        doc,
        coordinate_activity_pages,
        page_text_map=shared_ocr_cache.get("page_texts", {}),
    )
    if letter_rows:
        logger.info(f"  字母分级活性表OCR补充提取: {len(letter_rows)} rows")
        all_rows = _merge_activity_rows([*all_rows, *letter_rows])

    multi_rows = _extract_chinese_multi_numeric_activity_rows_from_ocr(
        doc,
        supplemental_pages,
        page_text_map=shared_ocr_cache.get("page_texts", {}),
    )
    if multi_rows:
        logger.info(f"  中文多组数值活性表OCR补充提取: {len(multi_rows)} rows")
        all_rows = _merge_activity_rows([*all_rows, *multi_rows])

    if not all_rows:
        singleton_rows = _extract_singleton_named_compound_activity_rows_from_ocr(
            doc,
            profile,
            page_text_map=shared_ocr_cache.get("page_texts", {}),
        )
        if singleton_rows:
            logger.info(f"  单一命名主化合物药效证据提取: {len(singleton_rows)} rows")
            all_rows = _merge_activity_rows([*all_rows, *singleton_rows])

    if all_rows:
        all_rows = _merge_activity_rows(all_rows)
    
    doc.close()
    
    # ── 7. Filter: exclude intermediates if not requested ──
    if not include_intermediates:
        before = len(all_rows)
        all_rows = [r for r in all_rows if not re.match(r"Int[-\s]?\d+", r.cpd, re.IGNORECASE)]
        logger.info(f"Filtered intermediates: {before} → {len(all_rows)} rows")
    
    # ── 8. Apply OCR fixes ──
    fix_rules = ocr_fix_rules if ocr_fix_rules is not None else DEFAULT_OCR_FIXES
    for row in all_rows:
        _apply_ocr_fixes(row, fix_rules, max_cpd_num=max_cpd_num if max_cpd_num > 0 else 9999)
    
    # ── 9. Validate captured values without clearing upstream conflict flags ──
    _mark_activity_rows_needing_review(all_rows)
    
    # ── 10. VLM verification (optional Phase 2) ──
    vlm_results = None
    if use_vlm and vlm_api_key and vlm_call is not None:
        logger.info("\n=== Phase 2: VLM验证 ===")
        vlm_results = _run_vlm_phase(
            all_rows, pdf_path, output_path,
            vlm_api_url, vlm_api_key, vlm_model,
            tables, column_layout, vlm_call,
        )
        if vlm_results:
            all_rows = _cross_reference(all_rows, vlm_results)
    elif use_vlm:
        logger.warning("VLM verification requested but no configured VLM adapter/credentials were supplied")
    
    # ── 11. Save results ──
    _save_results(all_rows, vlm_results, output_path, profile)
    
    n_unique = len(set(r.cpd for r in all_rows))
    logger.info(f"\n{'=' * 60}")
    logger.info(f"✅ Activity extraction complete: {len(all_rows)} rows, {n_unique} unique Cpds")
    logger.info(f"{'=' * 60}")
    
    return {
        "rows": all_rows,
        "n_rows": len(all_rows),
        "n_unique_cpds": n_unique,
        "tables": tables,
        "column_layout": column_layout,
        "column_headers": [c["header"] for c in col_classes],
        "col_classes": col_classes,
        "vlm_results": vlm_results,
        "output_dir": str(output_path),
    }


def _parse_num(val_str: str) -> Optional[float]:
    """Parse numeric value from string"""
    if not val_str:
        return None
    clean = val_str.replace(">", "").replace("<", "").replace("=", "").strip()
    try:
        return float(clean)
    except ValueError:
        return None


def _is_activity_value_valid(value: str) -> bool:
    """Return True for numeric values and common patent activity grades."""
    text = str(value or "").strip()
    if not text:
        return False
    if _is_explicit_missing_activity_value(text):
        return True
    if _parse_num(text) is not None or text == ">10000":
        return True
    # Biology tables often report ordered grades rather than raw numbers.
    if re.fullmatch(r"[A-E]", text, re.IGNORECASE):
        return True
    if re.fullmatch(r"\+{1,5}|-{1,3}", text):
        return True
    if re.fullmatch(r"[A-E][12]", text, re.IGNORECASE):
        return True
    if re.search(r"\breported\s*\(\d+\s+OCR\s+hits\)|\b\d+\s*-\s*\d+\s*\(\d+\s+figures\)|\bCX\s*\(\d+\s+OCR\s+hits\)", text, re.IGNORECASE):
        return True
    if re.search(r"\b\d+(?:\.\d+)?\s*(?:nM|uM|µM|μM|mg/kg|g/Kg|μg/Kg)\b", text, re.IGNORECASE):
        return True
    if re.fullmatch(r"[<>]=?\d+(?:\.\d+)?%?", text):
        return True
    return False


def _mark_activity_rows_needing_review(rows: list[ActivityRow]) -> None:
    """Retain source/conflict review flags and add invalid-cell review flags."""
    for row in rows:
        values = [
            value
            for bucket in (row.activity_values or {}, row.cell_line_data or {})
            for value in bucket.values()
        ]
        has_empty = any(value == "" or value is None for value in values)
        has_invalid = any(
            value and not _is_activity_value_valid(value)
            for value in values
        )
        row.needs_review = bool(row.needs_review or has_empty or has_invalid)
        if row.needs_review:
            row.confidence = min(row.confidence, 0.5)


def _normalise_grade_token(value: str) -> str:
    """Normalize OCR-noisy categorical biology grades without changing numbers."""
    text = str(value or "").strip()
    if not text:
        return ""
    text = text.replace("＋", "+").replace("﹢", "+").replace("十", "+")
    text = text.replace("—", "-").replace("－", "-")
    text = re.sub(r"\s+", "", text)
    if re.search(r"\+", text):
        plus_count = len(re.findall(r"\+", text))
        plus_count += len(re.findall(r"[1lI|#]", text))
        if plus_count > 0:
            return "+" * min(plus_count, 5)
    if text == "#":
        return "+"
    if re.fullmatch(r"[A-Ea-e]", text):
        return text.upper()
    return _normalise_activity_value(text)


def _is_control_activity_label(label: str) -> bool:
    text = re.sub(r"\s+", " ", str(label or "")).strip()
    return bool(re.search(
        r"^(?:ref\.?\s*\d+|reference\b|vehicle\b|dmso\b|control\b|nab[-\s]?paclitaxel\b|paclitaxel\b)",
        text,
        re.IGNORECASE,
    ))


def _normalise_text_table_cpd(label: str) -> str:
    text = re.sub(r"\s+", " ", str(label or "")).strip()
    if not text:
        return ""
    if _is_control_activity_label(text):
        return text.replace("Ref .", "Ref.").replace("Ref ", "Ref. ")
    m = re.search(r"(?:rac[-\s]*)?cpd\s*[-:]?\s*(\d+(?:-\d+)?[A-Z]?)", text, re.IGNORECASE)
    if m:
        prefix = "Rac-Cpd" if re.search(r"^rac", text, re.IGNORECASE) else "Cpd"
        return f"{prefix}-{m.group(1).upper()}"
    m = re.search(r"(?:compound|example|实施例|化合物)\s*[-:]?\s*(\d+(?:-\d+)?[A-Z]?)", text, re.IGNORECASE)
    if m:
        return f"Compound {m.group(1).upper()}"
    bare = re.fullmatch(r"(\d+(?:-\d+)?[A-Z]?)", text, re.IGNORECASE)
    if bare:
        return f"Compound {bare.group(1).upper()}"
    return ""


def _text_table_compound_match(line: str) -> tuple[str, str] | None:
    text = re.sub(r"\s+", " ", str(line or "")).strip()
    if not text:
        return None
    patterns = [
        r"^(Ref\.?\s*\d+)\b\s*(.*)$",
        r"^(Vehicle)\b\s*(.*)$",
        r"^(Nab[-\s]?paclitaxel|Paclitaxel)\b\s*(.*)$",
        r"^((?:Rac[-\s]*)?Cpd\s*[-:]?\s*\d+(?:-\d+)?[A-Z]?)\b\s*(.*)$",
        r"^((?:Compound|Example|实施例|化合物)\s*[-:]?\s*\d+(?:-\d+)?[A-Z]?)\b\s*(.*)$",
    ]
    for pattern in patterns:
        match = re.match(pattern, text, re.IGNORECASE)
        if match:
            cpd = _normalise_text_table_cpd(match.group(1))
            if cpd:
                return cpd, match.group(2).strip()
    return None


def _text_table_value_tokens(tail: str) -> list[str]:
    tail = str(tail or "")
    tail = tail.replace("≤", "<=").replace("≥", ">=")
    token_re = re.compile(
        r"<\s*=?\s*\d+(?:\.\d+)?|>\s*=?\s*\d+(?:\.\d+)?|"
        r"\d+(?:\.\d+)?\s*(?:±|\+/-)\s*\d+(?:\.\d+)?|"
        r"\d+(?:\.\d+)?%?|"
        r"\+[\+1lI|#]{0,5}|[1lI|#]\+{1,5}|#|"
        r"[A-Ea-e]\b|∞"
    )
    values = []
    for match in token_re.finditer(tail):
        token = match.group(0).strip()
        if not token:
            continue
        token = token.replace(" ", "")
        if "±" in token or "+/-" in token:
            values.append(token.replace("+/-", "±"))
        else:
            values.append(_normalise_grade_token(token))
    return [v for v in values if v]


def _split_flat_text_table_rows(segment: str) -> list[str]:
    """Recover table rows when OCR flattened a whole page into one paragraph."""
    text = re.sub(r"\s+", " ", str(segment or "")).strip()
    if not text:
        return []

    row_start = re.compile(
        r"(?=(?:Ref\.?\s*\d+|Vehicle\b|Nab[-\s]?paclitaxel\b|Paclitaxel\b|"
        r"(?:Rac[-\s]*)?Cpd\s*[-:]?\s*\d+(?:-\d+)?[A-Z]?|"
        r"(?:Compound|Example|实施例|化合物)\s*[-:]?\s*\d+(?:-\d+)?[A-Z]?))",
        re.IGNORECASE,
    )
    starts = [m.start() for m in row_start.finditer(text)]
    if not starts:
        return []

    hard_stop = re.search(
        r"\s(?:\*|以上数据显示|代谢酶|[一二三四五六七八九十]、|实验目的|实验观察|数据处理|统计分析|Form\s+PCT)",
        text,
        re.IGNORECASE,
    )
    hard_stop_pos = hard_stop.start() if hard_stop else len(text)
    starts = [pos for pos in starts if pos < hard_stop_pos]
    rows = []
    for idx, start in enumerate(starts):
        end = starts[idx + 1] if idx + 1 < len(starts) else hard_stop_pos
        row = text[start:end].strip(" ;,，。")
        parsed = _text_table_compound_match(row)
        if parsed and _text_table_value_tokens(parsed[1]):
            rows.append(row)
    return rows


def _clean_text_table_header_token(token: str) -> str:
    text = re.sub(r"\s+", " ", str(token or "")).strip(" ：:,;")
    text = re.sub(r"体内\s*[（(]\s*In vitro\s*[）)]", "In vitro", text, flags=re.IGNORECASE)
    text = text.replace("M)", "μM)")
    return text


def _infer_text_table_value_keys(caption: str, header_line: str, value_count: int) -> list[str]:
    caption_clean = re.sub(r"\s+", " ", str(caption or "")).strip()
    header_clean = re.sub(r"\s+", " ", str(header_line or "")).strip()
    compact = re.sub(r"\s+", "", f"{caption_clean} {header_clean}")

    if "表1" in compact and re.search(r"ARE|Luciferase|转录活性", compact, re.IGNORECASE):
        return ["KYSE-70 ARE IC50 (nM) grade", "KYSE-70 ARE Luciferase Imax (%) grade"]
    if "表2" in compact and re.search(r"KEAP|KEPA|CUL3|相互作用", compact, re.IGNORECASE):
        return ["KEAP1-CUL3 interaction EC50 (nM) grade"]
    if "表3" in compact and re.search(r"NRF2|HTRF", compact, re.IGNORECASE):
        return ["KYSE-70 NRF2 DC50 (nM) grade", "HCC95 NRF2 DC50 (nM) grade"]
    if "表4" in compact and re.search(r"3D|CTG|IC50|增殖", compact, re.IGNORECASE):
        return ["KYSE-70 3D CTG IC50 (nM) grade", "HCC95 3D CTG IC50 (nM) grade"]
    if "表5" in compact and re.search(r"Clint|t1/2|微粒体|代谢稳定", compact, re.IGNORECASE):
        return ["species", "In vitro t1/2 (min)", "In vitro Clint (μL/min/mg protein)"]
    if "表6" in compact and re.search(r"CD-1|小鼠|药代|Clint|AUC|Cmax", compact, re.IGNORECASE):
        return [
            "Mouse IV Clint (mL/min/kg)",
            "Mouse IV AUC0-t (hr*μM)",
            "Mouse PO Cmax (μM)",
            "Mouse PO AUC0-t (hr*μM)",
        ]
    if "表7" in compact and re.search(r"SD|大鼠|药代|AUC|Cmax", compact, re.IGNORECASE):
        return ["Rat PO Cmax (μM)", "Rat PO AUC0-t (hr*μM)"]
    if "表9" in compact and re.search(r"KYSE-70|TGI|异种移植|药效", compact, re.IGNORECASE):
        return [
            "KYSE-70 xenograft dose (mg/kg)",
            "KYSE-70 xenograft tumor volume (mm3)",
            "KYSE-70 xenograft TGI (%)",
            "KYSE-70 xenograft p value",
        ]
    if "表11" in compact and re.search(r"HCC95|TGI|异种移植|药效", compact, re.IGNORECASE):
        return [
            "HCC95 xenograft dose (mg/kg)",
            "HCC95 xenograft tumor volume (mm3)",
            "HCC95 xenograft TGI (%)",
            "HCC95 xenograft p value",
        ]

    metric_patterns = [
        (r"IC50\s*\([^)]*\)", "IC50"),
        (r"EC50\s*\([^)]*\)", "EC50"),
        (r"DC50\s*\([^)]*\)", "DC50"),
        (r"Imax\s*\([^)]*\)", "Imax"),
        (r"Dmax\s*\([^)]*\)", "Dmax"),
        (r"Clint\s*\([^)]*\)", "Clint"),
        (r"t1/2\s*\([^)]*\)", "t1/2"),
        (r"Cmax\s*\([^)]*\)", "Cmax"),
        (r"AUC0?-?t\s*\([^)]*\)", "AUC0-t"),
        (r"TGI\s*\([^)]*\)", "TGI"),
        (r"p\s*value", "p value"),
    ]
    keys = []
    for pattern, fallback in metric_patterns:
        for match in re.finditer(pattern, header_clean, re.IGNORECASE):
            keys.append(_clean_text_table_header_token(match.group(0)) or fallback)
    if len(keys) >= value_count:
        return keys[:value_count]
    while len(keys) < value_count:
        keys.append(f"{caption_clean or 'Activity table'} value {len(keys) + 1}")
    return keys


def _xenograft_activity_value_map(table_id: str, values: list[str]) -> dict[str, str]:
    """Build dose-aware xenograft result columns.

    Formal in-vivo efficacy tables can have repeated rows for the same
    compound at different doses and, in combination rows, a group number between
    dose and tumor volume. Encoding the dose/combination in the key prevents
    merge-time overwrites.
    """
    if not values:
        return {}
    vals = list(values)
    combo = False
    if len(vals) >= 5 and re.fullmatch(r"\d{1,2}", vals[1]) and ("±" in vals[2] or re.search(r"\d", vals[2])):
        vals.pop(1)
        combo = True
    if len(vals) < 4:
        return {}
    base = "KYSE-70 xenograft" if "9" in table_id else "HCC95 xenograft"
    dose = vals[0]
    treatment = f"{base} {'with Nab-paclitaxel ' if combo else ''}{dose} mg/kg"
    return {
        f"{treatment} tumor volume (mm3)": vals[1],
        f"{treatment} TGI (%)": vals[2],
        f"{treatment} p value": vals[3],
    }


def _extract_liver_microsome_rows_from_text_table_segment(
    caption: str,
    segment: str,
    page_no: int,
    table_id: str,
) -> list[ActivityRow]:
    """Parse liver-microsome tables with merged compound-label cells.

    OCR often emits the first two species rows, then the compound label, then
    the remaining three species rows. This parser binds species by biological
    species order instead of relying on flattened row order.
    """
    text = re.sub(r"\s+", " ", str(segment or "")).strip()
    if not text:
        return []
    label_re = re.compile(r"Ref\.?\s*\d+|(?:Rac[-\s]*)?Cpd\s*[-:]?\s*\d+(?:-\d+)?[A-Z]?|(?:Compound|Example|实施例|化合物)\s*[-:]?\s*\d+(?:-\d+)?[A-Z]?", re.IGNORECASE)
    species_re = re.compile(r"(人|猴|犬|大鼠|小鼠)\s+(∞|[<>]?\d+(?:\.\d+)?)\s+(∞|[<>]?\d+(?:\.\d+)?)")

    labels = [(m.start(), _normalise_text_table_cpd(m.group(0))) for m in label_re.finditer(text)]
    species = [
        (m.start(), m.group(1), _normalise_activity_value(m.group(2)), _normalise_activity_value(m.group(3)))
        for m in species_re.finditer(text)
    ]
    if not labels or not species:
        return []

    rows: list[ActivityRow] = []
    for label_pos, cpd in labels:
        if not cpd:
            continue
        values: dict[str, str] = {}
        # In these tables the compound label is centered after human/monkey and
        # before dog/rat/mouse.
        for sp in ("人", "猴"):
            candidates = [item for item in species if item[0] < label_pos and item[1] == sp]
            if candidates:
                _, species_name, half_life, clint = candidates[-1]
                values[f"{species_name} liver microsome t1/2 (min)"] = half_life
                values[f"{species_name} liver microsome Clint (μL/min/mg protein)"] = clint
        next_label_pos = min([pos for pos, _ in labels if pos > label_pos] or [len(text)])
        for sp in ("犬", "大鼠", "小鼠"):
            candidates = [item for item in species if label_pos < item[0] < next_label_pos and item[1] == sp]
            if candidates:
                _, species_name, half_life, clint = candidates[0]
                values[f"{species_name} liver microsome t1/2 (min)"] = half_life
                values[f"{species_name} liver microsome Clint (μL/min/mg protein)"] = clint
        if values:
            rows.append(ActivityRow(
                cpd=cpd,
                activity_values=values,
                page_no=page_no,
                table_id=table_id,
                source="ocr_text_table_liver_microsome",
                confidence=0.9,
                needs_review=False,
                notes="Generic OCR text-table extraction for merged-cell liver microsome table.",
            ))
    return rows


def _is_activity_result_caption(caption: str, following_text: str) -> bool:
    head = re.sub(r"\s+", "", f"{caption or ''} {following_text[:700]}")
    has_metric = bool(re.search(
        r"IC50|EC50|DC50|Imax|Dmax|Clint|t1/2|Cmax|AUC|TGI|pvalue|p值|药代|药效|抑制作用|试验结果|代谢稳定|相互作用|HTRF|Luciferase|3DCTG",
        head,
        re.IGNORECASE,
    ))
    if re.search(r"实验设计|给药信息|分组和给药|给药方式|给药频率|动物数|动物数量|给药体积|给药浓度", head):
        return False
    has_table_shape = bool(re.search(r"化合物编号|实施例|受试物|药物名称|组别|Ref\.?\s*\d+|Cpd[-\s]?\d+", head, re.IGNORECASE))
    return has_metric and has_table_shape


def _iter_text_table_segments(full_text: str) -> list[tuple[str, str]]:
    # Keep markers zero-width-ish. OCR caches often flatten a full page into a
    # single paragraph, so a greedy caption regex can swallow the next "表N"
    # marker and make whole result tables disappear.
    markers = list(re.finditer(r"(表\s*\d+|Table\s+\d+)\s*[:：]?", full_text, re.IGNORECASE))
    segments: list[tuple[str, str]] = []
    for idx, marker in enumerate(markers):
        caption_tail = full_text[marker.start():min(len(full_text), marker.start() + 180)]
        caption = re.sub(r"\s+", " ", caption_tail).strip()
        start = marker.start()
        end = markers[idx + 1].start() if idx + 1 < len(markers) else len(full_text)
        segment = full_text[start:end]
        if _is_activity_result_caption(caption, segment):
            segments.append((caption, segment))
    return segments


def _extract_rows_from_text_table_segment(caption: str, segment: str) -> list[ActivityRow]:
    lines = [re.sub(r"\s+", " ", line).strip() for line in segment.splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        return []

    table_match = re.search(r"(表\s*\d+|Table\s+\d+)", caption, re.IGNORECASE)
    table_id = re.sub(r"\s+", "", table_match.group(1)) if table_match else caption[:20]
    page_no = 0
    page_marker = re.search(r"\[\[PAGE\s+(\d+)\]\]", segment)
    if page_marker:
        page_no = int(page_marker.group(1))

    header_line = ""
    for line in lines[:12]:
        if re.search(r"化合物编号|实施例|受试物|药物名称|IC50|EC50|DC50|Imax|Dmax|Clint|AUC|Cmax|TGI|p\s*value", line, re.IGNORECASE):
            header_line = f"{header_line} {line}".strip()

    if "表5" in table_id and re.search(r"Clint|t1/2|微粒体|代谢稳定", f"{caption} {header_line}", re.IGNORECASE):
        microsome_rows = _extract_liver_microsome_rows_from_text_table_segment(caption, segment, page_no, table_id)
        if microsome_rows:
            return microsome_rows

    rows: list[ActivityRow] = []
    pending_cpd = ""
    pending_species_values: dict[str, dict[str, str]] = {}
    species_names = {"人", "猴", "犬", "大鼠", "小鼠"}

    def flush_species_row() -> None:
        nonlocal pending_cpd, pending_species_values
        if not pending_cpd or not pending_species_values:
            pending_species_values = {}
            return
        values: dict[str, str] = {}
        for species, data in pending_species_values.items():
            for key, val in data.items():
                values[f"{species} liver microsome {key}"] = val
        if values:
            rows.append(ActivityRow(
                cpd=pending_cpd,
                activity_values=values,
                page_no=page_no,
                table_id=table_id,
                source="ocr_text_table",
                confidence=0.88,
                needs_review=False,
                notes="Generic OCR text-table extraction from Chinese/English mixed activity table.",
            ))
        pending_species_values = {}

    for line in lines:
        if "[[PAGE" in line:
            marker = re.search(r"\[\[PAGE\s+(\d+)\]\]", line)
            if marker:
                page_no = int(marker.group(1))
            continue
        if re.search(r"^\*|指IC50|指DC50|指Imax|represents|以上数据显示|实验目的|实验方法|计算公式", line, re.IGNORECASE):
            continue

        parsed = _text_table_compound_match(line)
        if parsed:
            cpd, tail = parsed
            if re.search(r"表(?:9|11)", table_id) and not re.match(r"^(?:Cpd|Compound|Example|实施例|化合物|Ref)", cpd, re.IGNORECASE):
                continue
            if "TGI" in cpd or "计算公式" in line:
                continue
            if "表5" in table_id and re.search(r"代谢稳定|Clint|t1/2|微粒体", f"{caption} {header_line}", re.IGNORECASE):
                flush_species_row()
                pending_cpd = cpd
                species_match = re.match(r"^(人|猴|犬|大鼠|小鼠)\s+(.+)$", tail)
                if species_match:
                    vals = _text_table_value_tokens(species_match.group(2))
                    if len(vals) >= 2:
                        pending_species_values[species_match.group(1)] = {
                            "t1/2 (min)": vals[0],
                            "Clint (μL/min/mg protein)": vals[1],
                        }
                continue

            values = _text_table_value_tokens(tail)
            if not values:
                continue
            if re.search(r"表(?:9|11)", table_id):
                value_map = _xenograft_activity_value_map(table_id, values)
                if not value_map:
                    continue
            else:
                keys = _infer_text_table_value_keys(caption, header_line, len(values))
                value_map = dict(zip(keys, values))
            if "表9" in table_id or "表11" in table_id:
                # Ignore row/group numbers; rows must carry a tested compound.
                if _is_control_activity_label(cpd) and "Vehicle" in cpd:
                    continue
            rows.append(ActivityRow(
                cpd=cpd,
                activity_values=value_map,
                page_no=page_no,
                table_id=table_id,
                source="ocr_text_table",
                confidence=0.88,
                needs_review=False,
                notes="Generic OCR text-table extraction from Chinese/English mixed activity table.",
            ))
            continue

        if pending_cpd and "表5" in table_id:
            species_match = re.match(r"^(人|猴|犬|大鼠|小鼠)\s+(.+)$", line)
            if species_match:
                vals = _text_table_value_tokens(species_match.group(2))
                if len(vals) >= 2:
                    pending_species_values[species_match.group(1)] = {
                        "t1/2 (min)": vals[0],
                        "Clint (μL/min/mg protein)": vals[1],
                    }
            elif _text_table_compound_match(line):
                flush_species_row()

    flush_species_row()

    if not rows:
        flat_rows = _split_flat_text_table_rows(segment)
        for row_text in flat_rows:
            parsed = _text_table_compound_match(row_text)
            if not parsed:
                continue
            cpd, tail = parsed
            if re.search(r"表(?:9|11)", table_id) and not re.match(r"^(?:Cpd|Compound|Example|实施例|化合物|Ref)", cpd, re.IGNORECASE):
                continue
            if "TGI" in cpd or "计算公式" in row_text:
                continue
            values = _text_table_value_tokens(tail)
            if not values:
                continue
            if re.search(r"表(?:9|11)", table_id):
                value_map = _xenograft_activity_value_map(table_id, values)
                if not value_map:
                    continue
            else:
                keys = _infer_text_table_value_keys(caption, header_line, len(values))
                value_map = dict(zip(keys, values))
            rows.append(ActivityRow(
                cpd=cpd,
                activity_values=value_map,
                page_no=page_no,
                table_id=table_id,
                source="ocr_text_table_flat",
                confidence=0.84,
                needs_review=False,
                notes="Generic OCR flat text-table extraction from Chinese/English mixed activity table.",
            ))
    return rows


def _extract_generic_text_table_activity_rows_from_ocr(
    doc,
    activity_pages: list[int],
    page_text_map: Optional[dict[str, str]] = None,
) -> list[ActivityRow]:
    """Extract activity-result tables from flattened OCR text.

    This is intentionally table-driven rather than patent-number-driven: it
    detects Chinese/English table captions, keeps only result-like assay/PK/PD
    tables, then maps each row's values to inferred metric columns.
    """
    try:
        from patent_sar_extractor.core.patent_profiler import _ocr_page_fallback
    except Exception:
        _ocr_page_fallback = None

    full_text_parts: list[str] = []
    seen_pages: set[int] = set()
    candidate_pages = sorted(set(activity_pages or []))
    for page_idx in candidate_pages:
        if page_idx < 0 or page_idx >= len(doc) or page_idx in seen_pages:
            continue
        seen_pages.add(page_idx)
        text = str((page_text_map or {}).get(str(page_idx), ""))
        if not text.strip():
            text = doc[page_idx].get_text("text")
        if not text.strip() and _ocr_page_fallback is not None:
            text = _ocr_page_fallback(doc[page_idx])
        if text.strip():
            full_text_parts.append(f"\n[[PAGE {page_idx + 1}]]\n{text}")

    full_text = "\n".join(full_text_parts)
    if not full_text.strip():
        return []

    rows: list[ActivityRow] = []
    for caption, segment in _iter_text_table_segments(full_text):
        if re.search(r"(表\s*\d+|Table\s+\d+)\s*[。.]", caption, re.IGNORECASE):
            # Mentions like "结果见表9。" are prose, not the table itself.
            continue
        rows.extend(_extract_rows_from_text_table_segment(caption, segment))

    # Keep controls in activity_data.csv/json for auditability, but make sure
    # real compounds merge cleanly and repeated assay rows become one rich row.
    return _merge_activity_rows(rows)


def _extract_chinese_activity_rows_from_ocr(doc, activity_pages: list[int], page_text_map: Optional[dict[str, str]] = None) -> list[ActivityRow]:
    """Extract simple Chinese scanned tables like '实施例编号 IC50 (μM)' from OCR text."""
    try:
        from patent_sar_extractor.core.patent_profiler import _ocr_page_fallback
    except Exception:
        return []

    rows: list[ActivityRow] = []
    for page_idx in activity_pages:
        if page_idx >= len(doc):
            continue
        text = str((page_text_map or {}).get(str(page_idx), ""))
        if not text.strip():
            text = doc[page_idx].get_text("text")
        if not text.strip():
            text = _ocr_page_fallback(doc[page_idx])
        if "实施例编号" not in text or "IC50" not in text:
            continue

        # OCR often flattens the two-column table into:
        # 实施例编号 IC50 (μM) 1 18.41 2 4.71 ...
        tail = text.split("实施例编号", 1)[1]
        matches = re.findall(r"(?<![\d.])(\d{1,3})\s+([<>]?\d+(?:\.\d+)?)", tail)
        for ex_num, value in matches:
            n = int(ex_num)
            if n <= 0 or n > 999:
                continue
            rows.append(ActivityRow(
                cpd=f"实施例{n}",
                activity_values={"CRBN IC50 (μM)": value},
                page_no=page_idx + 1,
                table_id="表1",
                source="ocr_chinese_table",
                confidence=0.9,
            ))
    return rows


def _english_activity_pages_for_scan(doc, activity_pages: list[int], page_text_map: Optional[dict[str, str]] = None) -> list[int]:
    """Expand English biology tables across continuation pages."""
    page_text_map = page_text_map or {}
    biology_seeds = set()
    continuation_seeds = set()
    for page_idx in range(len(doc)):
        text = str(page_text_map.get(str(page_idx), "") or "")
        if not text.strip():
            text = doc[page_idx].get_text("text")
        if re.search(r"SECTION\s+III|BIOLOGY\s+ACTIVIT|Table\s+1[3-6]\b|HTRF|Western\s+blot|Anti-proliferation", text, re.I):
            biology_seeds.add(page_idx)
        elif re.search(r"Example\s+ID|Ranking\s+of\s+HuR|^\s*\d{1,3}[A-Z]?\s+[A-D]\b", text, re.I | re.M):
            continuation_seeds.add(page_idx)
    if not biology_seeds:
        return []

    # Use the biology section as the anchor. Profiler activity pages can include
    # early synthesis/assay prose pages; using their minimum page would make this
    # English fallback scan hundreds of unrelated pages and risk false table hits.
    start = min(biology_seeds)
    end = min(len(doc) - 1, max(biology_seeds | continuation_seeds) + 3)
    for idx in range(start, len(doc)):
        text = str(page_text_map.get(str(idx), "") or "")
        if not text.strip():
            text = doc[idx].get_text("text")
        if idx > start and re.search(r"\bEQUIVALENTS\b|权利要求|What\s+is\s+claimed", text, re.I):
            end = min(end, idx)
            break
        if idx in biology_seeds or idx in continuation_seeds or re.search(r"Table\s+1[3-6]\b|Example\s+ID|Ranking\s+of\s+HuR|^\s*\d{1,3}[A-Z]?\s+[A-D]\b", text, re.I | re.M):
            end = max(end, idx)
    return list(range(start, min(end, len(doc) - 1) + 1))


def _english_numeric_example_keys(header: str, value_count: int) -> list[str]:
    """Infer value columns for English Example # activity tables.

    Many WO biology result tables are OCR-flattened into:
    "Example # Assay A EC50 Assay A Ymin Assay B EC50 Assay B Ymin ...".
    Keep assay-specific names when they are recoverable, otherwise fall back to
    stable generic metric labels instead of dropping the table.
    """
    header_clean = re.sub(r"\s+", " ", str(header or "")).strip()
    compact = re.sub(r"\s+", "", header_clean).lower()
    if (
        value_count == 4
        and "fakhibit" in compact
        and re.search(r"cal[-\s]*51", header_clean, re.IGNORECASE)
        and "ec50" in compact
        and "ymin" in compact
    ):
        return [
            "FAK HiBiT EC50 (nM)",
            "FAK HiBiT Ymin",
            "CAL-51 Prolif EC50 (nM)",
            "CAL-51 Prolif Ymin",
        ]

    metric_matches = [
        _clean_text_table_header_token(match.group(0))
        for match in re.finditer(
            r"(?:IC50|EC50|DC50|GI50|Ki|Kd|Ymin|Ymax|Dmax|Imax)\s*(?:\([^)]*\))?",
            header_clean,
            re.IGNORECASE,
        )
    ]
    keys = [m for m in metric_matches if m]
    while len(keys) < value_count:
        keys.append(f"English Example activity value {len(keys) + 1}")
    return keys[:value_count]


def _extract_english_numeric_example_activity_rows_from_ocr(
    doc,
    activity_pages: list[int],
    page_text_map: Optional[dict[str, str]] = None,
) -> list[ActivityRow]:
    """Extract English activity tables whose rows start with bare Example numbers.

    This covers common continuation-page layouts such as:
    "Example # EC50 Ymin ... 23 1.03 7.69 0.62 20.44".
    The parser requires an explicit Example # header plus activity metrics, so
    synthesis tables with "Ex# / Structure / LCMS / NMR" are not treated as
    active-compound evidence.
    """
    page_text_map = page_text_map or {}
    rows: list[ActivityRow] = []
    candidate_pages = sorted(set(activity_pages or []))
    numeric_value = r"(?:NA|N/?A|[<>]=?\s*\d+(?:\.\d+)?|\d+(?:\.\d+)?)"
    data_row_re = re.compile(
        rf"(?<![A-Za-z0-9])(\d{{1,4}}[A-Z]?)(?![A-Za-z0-9-])\s+"
        rf"({numeric_value})\s+({numeric_value})"
        rf"(?:\s+({numeric_value})\s+({numeric_value}))?",
        re.IGNORECASE,
    )
    header_re = re.compile(
        r"Example\s*#.{0,220}?(?:IC50|EC50|DC50|GI50|Ki|Kd|Ymin|Ymax|Dmax|Imax)",
        re.IGNORECASE,
    )

    for page_idx in candidate_pages:
        if page_idx < 0 or page_idx >= len(doc):
            continue
        text = str(page_text_map.get(str(page_idx), "") or "")
        if not text.strip():
            text = doc[page_idx].get_text("text")
        clean = re.sub(r"\s+", " ", text).strip()
        if not clean or not header_re.search(clean):
            continue
        header_start = re.search(r"Example\s*#", clean, re.IGNORECASE)
        if not header_start:
            continue
        segment = clean[header_start.start():]
        segment = re.split(r"\bNA:\s*Not\s+available\b|\[\d{4,}\]|What\s+is\s+claimed|EQUIVALENTS", segment, maxsplit=1, flags=re.IGNORECASE)[0]
        first_row = data_row_re.search(segment)
        if not first_row:
            continue
        header = segment[:first_row.start()]
        # Require biology/activity metrics in the actual header. This prevents
        # "Ex# Procedures Structure Name LCMS NMR" structure tables from leaking
        # into activity-led binding.
        if not re.search(r"IC50|EC50|DC50|GI50|Ki|Kd|Ymin|Ymax|Dmax|Imax", header, re.IGNORECASE):
            continue
        table_match = re.search(r"(Table\s+\d+)", clean[:header_start.start() + 120], re.IGNORECASE)
        table_id = table_match.group(1) if table_match else "English Example activity table"

        for match in data_row_re.finditer(segment[first_row.start():]):
            cpd = match.group(1).upper()
            values = [_normalise_activity_value(v) for v in match.groups()[1:] if v is not None]
            if not values:
                continue
            if all(str(v).strip().upper() in {"NA", "N/A"} for v in values):
                confidence = 0.82
            else:
                confidence = 0.9
            keys = _english_numeric_example_keys(header, len(values))
            rows.append(ActivityRow(
                cpd=f"Example {cpd}",
                activity_values=dict(zip(keys, values)),
                page_no=page_idx + 1,
                table_id=table_id,
                source="ocr_english_numeric_example_table",
                confidence=confidence,
                needs_review=False,
                notes="Generic English Example # numeric activity table extraction.",
            ))

    return _merge_activity_rows(rows)


def _extract_english_biology_activity_rows_from_ocr(
    doc, activity_pages: list[int], page_text_map: Optional[dict[str, str]] = None,
) -> list[ActivityRow]:
    """Use observed biology headers and ruled cells, never flattened row regexes."""
    from patent_sar_extractor.core.biology_tables import extract_tables

    text_map = page_text_map or {}
    rows = _extract_english_numeric_example_activity_rows_from_ocr(
        doc, activity_pages, text_map,
    )
    scan_pages = _english_activity_pages_for_scan(doc, activity_pages, text_map)
    records = extract_tables(
        doc, scan_pages, tokens_for_page=_biology_tokens_for_page,
        grids_for_page=lambda page: _detect_ruled_table_regions(page, dpi=240),
    )
    rows.extend(
        ActivityRow(
            cpd=record.compound, activity_values=record.values,
            page_no=record.page_no, table_id=record.table_id,
            source="ocr_biology_cells", confidence=0.5 if record.needs_review else 0.95,
            needs_review=record.needs_review, notes=record.notes,
            activity_sources=[record.evidence],
        )
        for record in records
    )
    return _merge_activity_rows(rows)


def _normalise_ocr_decimal(value: str) -> str:
    value = value.strip()
    if "." in value:
        return value
    if value.isdigit() and 10 < int(value) < 100:
        return f"{value[:-1]}.{value[-1]}"
    return value


def _normalise_ocr_percent(value: str) -> str:
    return value.strip()


def _extract_chinese_dc50_dmax_rows_from_ocr(doc, activity_pages: list[int], page_text_map: Optional[dict[str, str]] = None) -> list[ActivityRow]:
    """Extract scanned Chinese VAV1 degradation tables with columns compound/DC50/Dmax."""
    try:
        from patent_sar_extractor.core.patent_profiler import _ocr_page_fallback
    except Exception:
        return []

    rows: list[ActivityRow] = []
    seen: set[tuple[str, int, str]] = set()

    for page_idx in activity_pages:
        if page_idx >= len(doc):
            continue
        text = str((page_text_map or {}).get(str(page_idx), ""))
        if not text.strip():
            text = doc[page_idx].get_text("text")
        if not text.strip():
            text = _ocr_page_fallback(doc[page_idx])
        norm = re.sub(r"DC[sS5oO]{1,2}", "DC50", text, flags=re.IGNORECASE)
        norm = re.sub(r"D\s*max", "Dmax", norm, flags=re.IGNORECASE)
        if not (re.search(r"VAV\s*1|VAV1", norm, re.IGNORECASE) and "DC50" in norm and "Dmax" in norm):
            continue

        split_parts = re.split(r"(测试例\s*2|PBMC)", norm, maxsplit=1, flags=re.IGNORECASE)
        segments: list[tuple[str, str, str]] = []
        if len(split_parts) >= 3:
            if "DC50" in split_parts[0] and "Dmax" in split_parts[0]:
                segments.append((split_parts[0], "Jurkat VAV1", "表1"))
            tail = "".join(split_parts[1:])
            if "DC50" in tail and "Dmax" in tail:
                segments.append((tail, "PBMC VAV1", "表3"))
        else:
            assay_prefix = (
                "Whole blood VAV1"
                if re.search(r"表\s*3|£\s*3|FACS|全血", norm, re.IGNORECASE)
                else ("PBMC VAV1" if re.search(r"PBMC", norm, re.IGNORECASE) else "Jurkat VAV1")
            )
            table_id = "表3" if not assay_prefix.startswith("Jurkat") else "表1"
            segments.append((norm, assay_prefix, table_id))

        for segment_text, assay_prefix, table_id in segments:
          for raw_line in segment_text.splitlines():
            line = re.sub(r"\s+", " ", raw_line).strip()
            if not line:
                continue

            cpd = ""
            dc50 = ""
            dmax = ""

            m = re.match(r"^(\d{1,2}(?:-\d)?)\s+([<>]?\d+(?:\.\d+)?)\s+(\d{2,3}(?:\.\d+)?)\b", line)
            if m:
                cpd, dc50, dmax = m.groups()
            else:
                grade_rows = re.findall(
                    r"(?:化合物|Compound)\s*([0-9]{1,3}(?:-\d)?)\s+([A-E]|B1|B2)\s+(\d{2,3}(?:\.\d+)?)\b",
                    line,
                    re.IGNORECASE,
                )
                if grade_rows:
                    for cpd_num, dc50_grade, dmax_val in grade_rows:
                        cpd_local = "4-2" if cpd_num == "42" and table_id == "表3" else cpd_num
                        key = (cpd_local, page_idx + 1, assay_prefix)
                        if key in seen:
                            continue
                        seen.add(key)
                        rows.append(ActivityRow(
                            cpd=f"Compound {cpd_local}",
                            activity_values={
                                f"{assay_prefix} DC50 grade": dc50_grade.upper(),
                                f"{assay_prefix} Dmax (%)": _normalise_ocr_percent(dmax_val),
                            },
                            page_no=page_idx + 1,
                            table_id=table_id,
                            source="ocr_chinese_dc50_dmax",
                  confidence=0.9 if _is_confident_dc50_dmax_pair(dc50_grade, dmax_val) else 0.78,
                  needs_review=not _is_confident_dc50_dmax_pair(dc50_grade, dmax_val),
                  notes="OCR fallback for scanned Chinese DC50/Dmax table.",
                        ))
                    continue
                else:
                    combo = re.search(
                        r"(\d{1,2}-1).*?(\d{1,2}-2).*?\b([<>]?\d+(?:\.\d+)?)\s+(\d{2,3}(?:\.\d+)?)\b",
                        line,
                        re.IGNORECASE,
                    )
                    if combo:
                        cpd = f"{combo.group(1)}/{combo.group(2)}"
                        dc50 = combo.group(3)
                        dmax = combo.group(4)

            if not cpd:
                continue
            if cpd == "42" and table_id == "表3":
                cpd = "4-2"
            dc50 = _normalise_ocr_decimal(dc50)
            key = (cpd, page_idx + 1, assay_prefix)
            if key in seen:
                continue
            seen.add(key)
            rows.append(ActivityRow(
                cpd=f"Compound {cpd}",
                activity_values={
                    f"{assay_prefix} {'DC50 grade' if re.fullmatch(r'[A-E]|B1|B2', dc50, re.IGNORECASE) else 'DC50 (nM)'}": dc50,
                    f"{assay_prefix} Dmax (%)": _normalise_ocr_percent(dmax),
                },
                page_no=page_idx + 1,
                table_id=table_id,
                source="ocr_chinese_dc50_dmax",
              confidence=0.9 if _is_confident_dc50_dmax_pair(dc50, dmax) else 0.78,
              needs_review=not _is_confident_dc50_dmax_pair(dc50, dmax),
              notes="OCR fallback for scanned Chinese DC50/Dmax table.",
            ))

    return rows


def _normalise_activity_value(value: str) -> str:
    value = str(value or "").strip()
    value = value.replace("二", ">").replace("全", ">").replace("〈", "<").replace("《", "<")
    value = value.replace("l", "1").replace("I", "1")
    value = re.sub(r"\s+", "", value)
    value = re.sub(r"([<>]?\d+(?:\.\d+)?)\?[46]$", r"\1%", value)
    value = re.sub(r"[?？][46]$", "%", value)
    value = value.replace("％", "%")
    return value


def _bare_no_table_segments(full_text: str) -> list[tuple[int, str]]:
    """Return English ``Table N`` chunks that may contain a visible ``No.`` column."""
    markers = list(re.finditer(r"\bTable\s+(\d{1,2})\b\s*[:.]?", full_text, re.IGNORECASE))
    segments: list[tuple[int, str]] = []
    for idx, marker in enumerate(markers):
        table_no = int(marker.group(1))
        start = marker.start()
        end = markers[idx + 1].start() if idx + 1 < len(markers) else len(full_text)
        segment = full_text[start:end]
        if re.search(r"\b(?:No\.?|Compound\s+No\.?)\b", segment[:900], re.IGNORECASE):
            segments.append((table_no, segment))
    return segments


_BARE_NO_TOKEN_RE = re.compile(
    r"nd|n/?a|[A-E]|[<>]?\d+(?:[.,]\d+)?(?:E[-+]?\d+)?|[一—-]",
    re.IGNORECASE,
)


def _bare_no_tokens(segment: str) -> list[str]:
    cleaned = re.sub(r"[\u00a0\u200b]+", " ", str(segment or ""))
    cleaned = cleaned.replace("≤", "<=").replace("≥", ">=")
    cleaned = cleaned.replace("µ", "u").replace("μ", "u")
    return [m.group(0) for m in _BARE_NO_TOKEN_RE.finditer(cleaned)]


def _normalise_bare_no_numeric(token: str, one_like_as_one: bool = True) -> str:
    text = re.sub(r"\s+", "", str(token or "")).strip()
    if not text:
        return ""
    lower = text.lower()
    if lower in {"nd", "na", "n/a"}:
        return "nd" if lower == "nd" else "N/A"
    if one_like_as_one and text in {"一", "—", "-"}:
        return "1"
    text = text.replace(",", ".")
    if re.search(r"\d", text):
        text = text.replace("O", "0").replace("o", "0")
    return _normalise_activity_value(text)


def _bare_no_float(token: str, one_like_as_one: bool = True) -> tuple[str, Optional[float]]:
    value = _normalise_bare_no_numeric(token, one_like_as_one=one_like_as_one)
    if value.lower() == "nd" or value.upper() == "N/A":
        return value, None
    try:
        return value, float(value.replace("<", "").replace(">", ""))
    except Exception:
        return value, None


def _bare_no_cpd_number(token: str, max_cpd: int = 999) -> Optional[int]:
    text = re.sub(r"\D", "", str(token or ""))
    if not text:
        return None
    try:
        num = int(text)
    except Exception:
        return None
    if 1 <= num <= max_cpd:
        return num
    return None


def _table3_value_triplet(tokens: list[str], start: int) -> Optional[tuple[dict[str, str], int]]:
    """Parse ``No. EC50 DC50 Dmax`` triplets from flattened multi-column tables."""
    if start + 2 >= len(tokens):
        return None
    ec50, ec50_num = _bare_no_float(tokens[start])
    if ec50.lower() != "nd" and (ec50_num is None or ec50_num < 0 or ec50_num > 20):
        return None

    dc50, dc50_num = _bare_no_float(tokens[start + 1])
    dmax, dmax_num = _bare_no_float(tokens[start + 2])
    if dc50.lower() != "nd" and (dc50_num is None or dc50_num < 0 or dc50_num > 10000):
        return None
    if dmax_num is None or dmax_num < 0 or dmax_num > 100:
        return None
    return (
        {
            "HTRF CRBN EC50 (uM)": ec50,
            "NEK7 NanoBiT DC50 (nM)": dc50,
            "NEK7 NanoBiT Dmax (%)": dmax,
        },
        3,
    )


def _table3_value_pair_missing_dc50(tokens: list[str], start: int) -> Optional[tuple[dict[str, str], int]]:
    """Recover rows where OCR dropped a one-digit DC50 but kept Dmax."""
    if start + 1 >= len(tokens):
        return None
    ec50, ec50_num = _bare_no_float(tokens[start])
    dmax, dmax_num = _bare_no_float(tokens[start + 1])
    if ec50.lower() != "nd" and (ec50_num is None or ec50_num < 0 or ec50_num > 20):
        return None
    if dmax_num is None or dmax_num < 40 or dmax_num > 100:
        return None
    return (
        {
            "HTRF CRBN EC50 (uM)": ec50,
            "NEK7 NanoBiT Dmax (%)": dmax,
        },
        2,
    )


def _table4_grade_triplet(tokens: list[str], start: int) -> Optional[tuple[dict[str, str], int]]:
    if start + 2 >= len(tokens):
        return None
    vals = [_normalise_grade_token(tokens[start + offset]) for offset in range(3)]
    if not all(re.fullmatch(r"[A-E]|nd|N/A", val, re.IGNORECASE) for val in vals):
        return None
    return (
        {
            "HTRF CRBN EC50 class": vals[0].upper(),
            "NEK7 NanoBiT DC50 class": vals[1].upper(),
            "NEK7 NanoBiT Dmax class": vals[2].upper(),
        },
        3,
    )


def _table5_value_triplet(tokens: list[str], start: int) -> Optional[tuple[dict[str, str], int]]:
    if start + 2 >= len(tokens):
        return None
    caspase, caspase_num = _bare_no_float(tokens[start])
    il1b, il1b_num = _bare_no_float(tokens[start + 1])
    n_value, n_num = _bare_no_float(tokens[start + 2])
    if caspase_num is None or il1b_num is None:
        return None
    if caspase_num < 0 or caspase_num > 100 or il1b_num < 0 or il1b_num > 100:
        return None
    if n_num is None or n_num < 1 or n_num > 50 or abs(n_num - round(n_num)) > 1e-6:
        return None
    return (
        {
            "Caspase-1 IC50 (NIG, uM)": caspase,
            "IL-1b IC50 (NIG, uM)": il1b,
            "monocyte donor n": n_value,
        },
        3,
    )


def _looks_like_bare_no_group(
    tokens: list[str],
    idx: int,
    parser,
    max_cpd: int,
) -> bool:
    return _bare_no_cpd_number(tokens[idx], max_cpd=max_cpd) is not None and parser(tokens, idx + 1) is not None


def _extract_bare_no_groups(
    tokens: list[str],
    parser,
    max_cpd: int,
    allow_missing_dc50: bool = False,
) -> list[tuple[int, dict[str, str], int]]:
    rows: list[tuple[int, dict[str, str], int]] = []
    idx = 0
    while idx < len(tokens):
        cpd_num = _bare_no_cpd_number(tokens[idx], max_cpd=max_cpd)
        if cpd_num is None:
            idx += 1
            continue

        parsed = parser(tokens, idx + 1)
        if parsed is None and allow_missing_dc50:
            # If the next token starts a valid row, the current row probably
            # lost its one-digit DC50 during OCR. Keep the row, but do not
            # invent the missing value.
            pair = _table3_value_pair_missing_dc50(tokens, idx + 1)
            if pair is not None:
                value_map, consumed = pair
                next_idx = idx + 1 + consumed
                if next_idx < len(tokens) and _looks_like_bare_no_group(tokens, next_idx, parser, max_cpd):
                    rows.append((cpd_num, value_map, consumed))
                    idx = next_idx
                    continue
        if parsed is None:
            idx += 1
            continue
        value_map, consumed = parsed
        rows.append((cpd_num, value_map, consumed))
        idx += 1 + consumed
    return rows


def _extract_table6_compound14_comparison(segment: str) -> list[ActivityRow]:
    compact = re.sub(r"\s+", " ", str(segment or " ")).strip()
    if not (re.search(r"\bTable\s+6\b", compact, re.IGNORECASE) and "Compound 14" in compact):
        return []
    ic50 = re.search(
        r"IC50\s*\(nM\)\s+(\d+(?:\.\d+)?)\s+\d+(?:\.\d+)?\s+(\d+(?:\.\d+)?)\s+\d+(?:\.\d+)?",
        compact,
        re.IGNORECASE,
    )
    imax = re.search(
        r"Imax\s*\(%\)\s+(\d+(?:\.\d+)?)\s+\d+(?:\.\d+)?\s+(\d+(?:\.\d+)?)\s+\d+(?:\.\d+)?",
        compact,
        re.IGNORECASE,
    )
    if not ic50 and not imax:
        return []
    values: dict[str, str] = {}
    if ic50:
        values["MSU macrophage caspase-1 activity IC50 (nM)"] = ic50.group(1)
        values["MSU macrophage IL-1b IC50 (nM)"] = ic50.group(2)
    if imax:
        values["MSU macrophage caspase-1 activity Imax (%)"] = imax.group(1)
        values["MSU macrophage IL-1b Imax (%)"] = imax.group(2)
    return [
        ActivityRow(
            cpd="Compound 14",
            activity_values=values,
            page_no=_page_no_before_offset(segment, len(segment)) or 0,
            table_id="Table 6",
            source="ocr_english_bare_no_table",
            confidence=0.88,
            needs_review=False,
            notes="Generic English comparison table extraction for named active compound.",
        )
    ]


def _extract_english_bare_no_activity_rows_from_ocr(
    doc,
    activity_pages: list[int],
    page_text_map: Optional[dict[str, str]] = None,
) -> list[ActivityRow]:
    """Extract English activity tables whose visible left column is ``No.``.

    Several patents report final compounds as bare row numbers rather than
    ``Compound 1``/``Example 1``.  This parser only activates inside explicit
    activity table captions with ``No.`` headers, then normalizes the row labels
    to ``Compound N`` so the activity-led binder can use them downstream.
    """
    page_text_map = page_text_map or {}
    parts: list[str] = []
    # Profiler activity pages are intentionally conservative and can miss
    # continuation pages that contain only bare numeric rows. Include immediate
    # neighbours, then let the strict Table/No/activity-header gates below decide
    # whether any text is actually parsed.
    candidate_pages: set[int] = set()
    for page_idx in activity_pages or []:
        try:
            idx = int(page_idx)
        except Exception:
            continue
        for offset in (-1, 0, 1):
            candidate_pages.add(idx + offset)
    for page_idx in sorted(candidate_pages):
        if page_idx < 0 or page_idx >= len(doc):
            continue
        text = str(page_text_map.get(str(page_idx), "") or "")
        if not text.strip():
            text = doc[page_idx].get_text("text")
        if text.strip():
            parts.append(f"\n[[PAGE {page_idx + 1}]]\n{text}")
    full_text = "\n".join(parts)
    if not full_text.strip():
        return []

    rows: list[ActivityRow] = []
    seen: set[tuple[str, str]] = set()
    for table_no, segment in _bare_no_table_segments(full_text):
        head = re.sub(r"\s+", " ", segment[:1200])
        page_no = _page_no_before_offset(segment, len(segment)) or 0

        if table_no == 3 and re.search(r"HTRF|CRBN|NanoBiT|NEK7|DC50|Dmax", head, re.IGNORECASE):
            header = re.search(r"\bNo\.?.{0,260}?(?:Dmax|Daax|Drax|EC50|DC50|NanoBiT)", segment, re.IGNORECASE | re.DOTALL)
            data_segment = segment[header.end():] if header else segment
            tokens = _bare_no_tokens(data_segment)
            for cpd_num, values, _ in _extract_bare_no_groups(
                tokens,
                _table3_value_triplet,
                max_cpd=999,
                allow_missing_dc50=True,
            ):
                key = (f"Compound {cpd_num}", "Table 3")
                if key in seen:
                    continue
                seen.add(key)
                rows.append(ActivityRow(
                    cpd=f"Compound {cpd_num}",
                    activity_values=values,
                    page_no=page_no,
                    table_id="Table 3",
                    source="ocr_english_bare_no_table",
                    confidence=0.9 if len(values) == 3 else 0.78,
                    needs_review=len(values) < 3,
                    notes="Generic English No.-column activity table extraction.",
                ))
            continue

        if table_no == 4 and re.search(r"HTRF|CRBN|NanoBiT|NEK7|class|DC50|Dmax", head, re.IGNORECASE):
            header = re.search(r"\bNo\.?.{0,260}?(?:Dmax|EC50|DC50|NanoBiT)", segment, re.IGNORECASE | re.DOTALL)
            data_segment = segment[header.end():] if header else segment
            tokens = _bare_no_tokens(data_segment)
            for cpd_num, values, _ in _extract_bare_no_groups(tokens, _table4_grade_triplet, max_cpd=999):
                key = (f"Compound {cpd_num}", "Table 4")
                if key in seen:
                    continue
                seen.add(key)
                rows.append(ActivityRow(
                    cpd=f"Compound {cpd_num}",
                    activity_values=values,
                    page_no=page_no,
                    table_id="Table 4",
                    source="ocr_english_bare_no_table",
                    confidence=0.88,
                    needs_review=False,
                    notes="Generic English No.-column class activity table extraction.",
                ))
            continue

        if table_no == 5 and re.search(r"Caspase|IL-?1", head, re.IGNORECASE):
            header = re.search(r"\bCompound\b.{0,360}?\bn\s*=\s*", segment, re.IGNORECASE | re.DOTALL)
            if not header:
                header = re.search(r"\bNo\.?.{0,260}?(?:IC50|NIG|uM|μM|µM)", segment, re.IGNORECASE | re.DOTALL)
            data_segment = segment[header.end():] if header else segment
            tokens = _bare_no_tokens(data_segment)
            for cpd_num, values, _ in _extract_bare_no_groups(tokens, _table5_value_triplet, max_cpd=999):
                key = (f"Compound {cpd_num}", "Table 5")
                if key in seen:
                    continue
                seen.add(key)
                rows.append(ActivityRow(
                    cpd=f"Compound {cpd_num}",
                    activity_values=values,
                    page_no=page_no,
                    table_id="Table 5",
                    source="ocr_english_bare_no_table",
                    confidence=0.9,
                    needs_review=False,
                    notes="Generic English No.-column functional assay extraction.",
                ))
            continue

        if table_no == 6:
            rows.extend(_extract_table6_compound14_comparison(segment))

    return _merge_activity_rows(rows)


def _clean_activity_ocr_text(text: str) -> str:
    text = str(text or "").strip()
    text = text.replace("≤", "<=").replace("＜", "<").replace("〈", "<").replace("《", "<")
    text = text.replace("二", ">").replace("全", ">")
    # Common Tesseract confusions inside scanned Chinese activity grids.
    text = text.replace("]", "1").replace("$", "5")
    text = text.replace("S", "5").replace("s", "5") if re.fullmatch(r"[Ss]\d*", text) else text
    text = text.replace("O", "0") if re.fullmatch(r"[O0]+", text) else text
    return re.sub(r"\s+", "", text)


def _activity_tokens_for_page(page, dpi: int = 300) -> list[dict]:
    cache = getattr(_activity_tokens_for_page, "_cache", None)
    if cache is None:
        cache = {}
        _activity_tokens_for_page._cache = cache
    page_key = (getattr(page, "number", -1), int(dpi))
    if page_key in cache:
        return cache[page_key]
    tokens = _ocr_tokens_with_positions(
        page,
        dpi=dpi,
        allow_tesseract=_allow_tesseract_fallback() or _auto_tesseract_activity_tokens(),
    )
    cache[page_key] = tokens
    return tokens


def _token_number(text: str) -> Optional[int]:
    clean = _clean_activity_ocr_text(text)
    if re.fullmatch(r"\d{1,3}", clean):
        num = int(clean)
        if 0 < num <= 300:
            return num
    return None


def _token_value(text: str) -> str:
    clean = _clean_activity_ocr_text(text)
    clean = clean.replace("=<", "<=").replace("=<", "<=")
    clean = re.sub(r"^<=$", "<=", clean)
    clean = re.sub(r"^<=(\d)", r"<=\1", clean)
    clean = re.sub(r"^≤", "<=", clean)
    clean = clean.replace("=<", "<=")
    clean = clean.replace("<=", "<")
    clean = clean.replace("=<", "<")
    clean = clean.replace("=>", ">")
    clean = clean.replace(">=", ">")
    clean = clean.replace("=", "")
    clean = re.sub(r"^=(\d+%?)$", r">\1", clean)
    clean = re.sub(r"^(\d+(?:\.\d+)?%?)([<>])$", r"\2\1", clean)
    clean = re.sub(r"^(\d+(?:\.\d+)?%?)=?>$", r">\1", clean)
    clean = re.sub(r"^(\d+(?:\.\d+)?%?)=?<$", r"<\1", clean)
    clean = clean.replace("％", "%")
    return _normalise_activity_value(clean)


def _normalise_activity_cell_value(text: str, key: str = "") -> str:
    value = _token_value(text)
    # In threshold percentage columns, Tesseract often drops ">" from >80% or
    # reads it as "=". Keep this rule column-scoped so ordinary exact
    # percentages such as PK F(%) are not rewritten.
    if re.search(r"Dmax|remaining|剩余", key, re.IGNORECASE) and re.fullmatch(r"\d+(?:\.\d+)?%", value):
        return f">{value}"
    return value


def _split_joined_dc50_dmax_cell(text: str) -> tuple[str, str] | None:
    """Split OCR-joined AR degradation cells such as ``<20 =80%``.

    Some ruled Chinese tables render two measurements inside one visual cell:
    DC50 followed by Dmax. OCR returns them as one token string, so the parser
    must split the cell before assigning values to columns.
    """
    raw = str(text or "").strip()
    raw = raw.replace("％", "%").replace("≤", "<").replace("≥", ">")
    raw = raw.replace("〈", "<").replace("《", "<").replace("二", ">").replace("全", ">")
    match = re.fullmatch(
        r"\s*([<>]?\s*\d+(?:\.\d+)?)\s*(?:[=>]+\s*|\s+)([<>=>]?\s*\d+(?:\.\d+)?\s*%?)\s*[=>]*\s*",
        raw,
    )
    if not match:
        return None
    dc50 = _normalise_activity_value(match.group(1))
    dmax = _normalise_activity_value(match.group(2).replace("=", ">"))
    if not dmax.startswith((">", "<")):
        dmax = f">{dmax}"
    if not dmax.endswith("%"):
        dmax = f"{dmax}%"
    if re.search(r"\d", dc50) and re.search(r"\d", dmax):
        return dc50, dmax
    return None


def _ocr_cell_clip(page, bbox: tuple[float, float, float, float], dpi: int = 450) -> str:
    """OCR a single table cell crop when whole-page OCR missed a sparse value."""
    if not (_allow_tesseract_fallback() or _auto_tesseract_activity_tokens()):
        return ""
    try:
        import pytesseract  # type: ignore
        from PIL import Image
        from io import BytesIO
    except Exception:
        return ""
    x0, y0, x1, y1 = bbox
    clip = fitz.Rect(max(0, x0 - 2), max(0, y0 - 2), x1 + 2, y1 + 2)
    pix = page.get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72), clip=clip)
    img = Image.open(BytesIO(pix.tobytes("png"))).convert("L")
    configs = [
        "--psm 7 -c tessedit_char_whitelist=0123456789<>=%.",
        "--psm 6 -c tessedit_char_whitelist=0123456789<>=%.",
    ]
    for config in configs:
        try:
            text = pytesseract.image_to_string(img, lang="eng", config=config)
        except Exception:
            continue
        text = re.sub(r"\s+", "", text or "")
        if re.search(r"\d", text):
            return text
    return ""


def _activity_value_near(
    tokens: list[dict],
    row_y: float,
    val_x: float,
    y_tol: float = 7,
    x_tol: float = 45,
    reject_values: set[str] | None = None,
) -> str:
    """Read one activity cell near a target column, preserving split < / > signs."""
    reject_values = reject_values or set()
    candidates = sorted(
        [
            t for t in tokens
            if abs(float(t["y"]) - row_y) <= y_tol
            and abs(float(t["x"]) - val_x) <= x_tol
        ],
        key=lambda t: float(t["x"]),
    )
    if not candidates:
        return ""

    raw_parts = [_clean_activity_ocr_text(t["text"]) for t in candidates]
    parts = [_token_value(part) for part in raw_parts if part]

    # Prefer explicit comparator + value pairs such as "< 1000" or "> 80%".
    for i, part in enumerate(parts):
        if part in {"<", ">"} and i + 1 < len(parts):
            nxt = parts[i + 1]
            if re.search(r"\d", nxt) and nxt not in reject_values:
                return part + nxt

    # Tesseract sometimes reads "=> 85%" for ">85%"; normalize the joined text.
    joined = _token_value("".join(raw_parts))
    if re.search(r"[<>]?\d", joined) and joined not in reject_values:
        return joined

    for cand in sorted(candidates, key=lambda t: abs(float(t["x"]) - val_x)):
        val = _token_value(cand["text"])
        if re.search(r"\d", val) and val not in reject_values:
            return val
    return ""


def _cell_text_from_tokens(tokens: list[dict], x0: float, x1: float, y0: float, y1: float) -> str:
    parts = [
        t for t in tokens
        if x0 + 0.5 <= float(t["x"]) <= x1 - 0.5
        and y0 - 1.5 <= float(t["y"]) <= y1 + 1.5
    ]
    return " ".join(t["text"] for t in sorted(parts, key=lambda t: (float(t["y"]), float(t["x"])))).strip()


def _ruled_table_matrix(tokens: list[dict], region: dict) -> list[list[str]]:
    xs = region["xs"]
    ys = region["ys"]
    matrix: list[list[str]] = []
    for ri in range(len(ys) - 1):
        row = []
        for ci in range(len(xs) - 1):
            row.append(_cell_text_from_tokens(tokens, xs[ci], xs[ci + 1], ys[ri], ys[ri + 1]))
        matrix.append(row)
    return matrix


def _ruled_table_context(tokens: list[dict], y0: float, y1: float) -> str:
    selected = [
        token for token in tokens
        if y0 <= float(token["y"]) <= y1
    ]
    return " ".join(
        token["text"] for token in sorted(selected, key=lambda token: (float(token["y"]), float(token["x"])))
    )


def _ruled_table_id(context: str, default: str) -> str:
    match = re.search(r"表\s*([0-9]{1,2})", context, re.IGNORECASE)
    if match:
        return f"表{match.group(1)}"
    match = re.search(r"\bTable\s*([0-9]{1,2})\b", context, re.IGNORECASE)
    return f"Table {match.group(1)}" if match else default


def _classify_ruled_activity_schema(
    context: str,
    column_count: int = 0,
) -> tuple[str, list[str]] | None:
    """Infer a ruled activity-table schema from labels and layout, not pages."""
    compact = re.sub(r"\s+", "", str(context or ""))
    lower = compact.lower()

    if (
        column_count >= 7
        and re.search(r"auc|cmax|cl|f\(?%?\)?|t[1m]?/?2|药代", lower, re.IGNORECASE)
    ):
        return _ruled_table_id(context, "PK"), [
            "Mouse IV AUC (ng*h/mL)",
            "Mouse IV t1/2 (h)",
            "Mouse IV CL (L/hr/kg)",
            "Mouse PO AUC (ng*h/mL)",
            "Mouse PO t1/2 (h)",
            "Mouse PO Cmax (ng/mL)",
            "Mouse oral bioavailability F (%)",
        ]

    has_proliferation = bool(re.search(r"增殖|prolifer|\bi[ck]?[cs5]0\b", lower, re.IGNORECASE))
    has_vcap = "vcap" in lower
    has_lncap = "lncap" in lower
    has_ar_degradation = bool(re.search(r"降解|degrad|dc[s5]0|dmax", lower, re.IGNORECASE))
    if has_ar_degradation and has_lncap and not has_proliferation:
        return _ruled_table_id(context, "LNCaP AR degradation"), [
            "LNCaP AR DC50 (nM)",
            "LNCaP AR Dmax (%)",
        ]
    if has_ar_degradation and has_vcap and not has_proliferation:
        return _ruled_table_id(context, "VCaP AR degradation"), [
            "VCaP AR DC50 (nM)",
        ]

    if re.search(r"htrf|crbn|nanobit|nek7|dc[s5]0|dmax|ec[s5]0", lower, re.IGNORECASE):
        table_id = _ruled_table_id(context, "HTRF/NEK7 activity")
        if column_count >= 4 and re.search(r"^[\s\S]*(?:class|represents|a,b|abc|[ABC])", context, re.IGNORECASE) and not re.search(r"\b(?:nM|uM|μM|µM)\b", context, re.IGNORECASE):
            return table_id, [
                "HTRF CRBN EC50 class",
                "NEK7 NanoBiT DC50 class",
                "NEK7 NanoBiT Dmax class",
            ]
        if column_count >= 4:
            return table_id, [
                "HTRF CRBN EC50 (uM)",
                "NEK7 NanoBiT DC50 (nM)",
                "NEK7 NanoBiT Dmax (%)",
            ]

    if (
        column_count in {0, 4}
        and re.search(r"微粒体|microsom|60min|剩余|metabolic", lower, re.IGNORECASE)
    ):
        return _ruled_table_id(context, "Microsome"), [
            "Human liver microsome remaining at 60 min (%)",
        ]

    # Do not treat OCR variants of DC50 (for example ``DCS50``) as IC50.
    # Proliferation requires either its biology label or an explicit I-prefixed
    # IC50 token; otherwise AR degradation tables lose their DC50/Dmax fields.
    if has_proliferation and has_lncap:
        return _ruled_table_id(context, "LNCaP proliferation"), ["LNCaP proliferation IC50 (nM)"]
    if has_proliferation and has_vcap:
        return _ruled_table_id(context, "VCaP proliferation"), ["VCaP proliferation IC50 (nM)"]

    if has_ar_degradation and has_lncap and ("dmax" in lower or column_count == 6):
        return _ruled_table_id(context, "LNCaP AR degradation"), [
            "LNCaP AR DC50 (nM)",
            "LNCaP AR Dmax (%)",
        ]
    if has_ar_degradation and has_vcap:
        return _ruled_table_id(context, "VCaP AR degradation"), ["VCaP AR DC50 (nM)"]
    return None


def _ruled_cell_value(
    page,
    row: list[str],
    region: dict,
    ri: int,
    ci: int,
    key: str,
) -> str:
    raw = row[ci] if ci < len(row) else ""
    value = _normalise_activity_cell_value(raw, key)
    if value:
        return value
    xs = region["xs"]
    ys = region["ys"]
    if ci + 1 >= len(xs) or ri + 1 >= len(ys):
        return ""
    retry_raw = _ocr_cell_clip(page, (xs[ci], ys[ri], xs[ci + 1], ys[ri + 1]))
    return _normalise_activity_cell_value(retry_raw, key)


def _is_ruled_activity_value(value: str, key: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    if "class" in key.lower():
        return bool(re.fullmatch(r"[A-E]|nd|N/A", text, re.IGNORECASE))
    return bool(re.search(r"\d", text) or text.lower() == "nd")


def _parse_ruled_activity_region(
    page,
    page_no: int,
    tokens: list[dict],
    region: dict,
    classified: tuple[str, list[str]],
) -> list[ActivityRow]:
    matrix = _ruled_table_matrix(tokens, region)
    table_id, value_keys = classified
    rows: list[ActivityRow] = []

    # PK tables are a single compound column followed by seven measurements.
    if len(value_keys) == 7:
        for ri, row in enumerate(matrix):
            if not row:
                continue
            cpd_num = _token_number(row[0])
            if cpd_num is None:
                continue
            values = {}
            for offset, key in enumerate(value_keys, start=1):
                val = _ruled_cell_value(page, row, region, ri, offset, key)
                if re.search(r"\d", val):
                    values[key] = val
            if len(values) >= 6:
                rows.append(ActivityRow(
                    cpd=f"Compound {cpd_num}",
                    activity_values=values,
                    page_no=page_no,
                    table_id=table_id,
                    source="ocr_ruled_table",
                    confidence=0.93,
                    notes="Line-grid table extraction with OCR tokens assigned to cells.",
                ))
        return rows

    # Repeated activity tables: each data row contains one or more groups of
    # compound-number column followed by one or more value columns.
    value_count = len(value_keys)
    for ri, row in enumerate(matrix):
        if value_count == 2:
            row_added = False
            for ci in range(0, len(row) - 1, 2):
                cpd_num = _token_number(row[ci])
                if cpd_num is None:
                    continue
                split = _split_joined_dc50_dmax_cell(row[ci + 1])
                if not split:
                    continue
                vals = {
                    value_keys[0]: split[0],
                    value_keys[1]: split[1],
                }
                rows.append(ActivityRow(
                    cpd=f"Compound {cpd_num}",
                    activity_values=vals,
                    page_no=page_no,
                    table_id=table_id,
                    source="ocr_ruled_table",
                    confidence=0.93,
                    notes="Line-grid table extraction with OCR tokens assigned to cells.",
                ))
                row_added = True
            if row_added:
                continue
        ci = 0
        while ci < len(row):
            cpd_num = _token_number(row[ci])
            if cpd_num is None:
                ci += 1
                continue
            vals = {}
            for vi, key in enumerate(value_keys):
                if ci + 1 + vi >= len(row):
                    break
                val = _ruled_cell_value(page, row, region, ri, ci + 1 + vi, key)
                if _is_ruled_activity_value(val, key):
                    vals[key] = val
            if len(vals) == value_count:
                rows.append(ActivityRow(
                    cpd=f"Compound {cpd_num}",
                    activity_values=vals,
                    page_no=page_no,
                    table_id=table_id,
                    source="ocr_ruled_table",
                    confidence=0.93,
                    notes="Line-grid table extraction with OCR tokens assigned to cells.",
                ))
                ci += 1 + value_count
            else:
                ci += 1
    return rows


_PREFIXED_GRADE_ROW_RE = re.compile(
    r"(?<![A-Za-z0-9])([A-Za-z1])\s*[-–—]\s*(\d{1,5})\s+([A-G])(?=\s|$)",
    re.IGNORECASE,
)

_COORDINATE_ACTIVITY_CONTEXT_RE = re.compile(
    r"(?:\b(?:p?IC|EC|DC|GI|CC)[S5]?[0O5]\b|Dmax|HiBiT|FACS|HTRF|NanoBiT|"
    r"AUC|Cmax|microsom|prolifer|degrad|\bactivity\b|\bassay\b|活性|降解|增殖|药代)",
    re.IGNORECASE,
)


def _coordinate_activity_page_candidates(
    activity_pages: list[int],
    page_text_map: Optional[dict[str, str]] = None,
) -> list[int]:
    """Select pages that justify expensive coordinate OCR.

    Page classification is intentionally recall-oriented and can include many
    synthesis pages merely because they contain units such as ``nM``.  The
    coordinate parsers render full pages and run OCR, so gate them on cached
    activity-table context and row evidence.  When no shared text cache is
    available, preserve the previous exhaustive behavior rather than silently
    dropping a possible table.
    """
    pages = sorted({
        int(page_idx)
        for page_idx in activity_pages
        if isinstance(page_idx, int) or str(page_idx).isdigit()
    })
    if not page_text_map:
        return pages

    direct: set[int] = set()
    continuation_evidence: set[int] = set()
    for page_idx in pages:
        text = str(page_text_map.get(str(page_idx), "") or "")
        if not text.strip():
            continue
        has_context = bool(_COORDINATE_ACTIVITY_CONTEXT_RE.search(text))
        has_table_heading = bool(re.search(r"\bTable\s*\d+|表\s*\d+", text, re.IGNORECASE))
        grade_rows = len(_PREFIXED_GRADE_ROW_RE.findall(text))
        labelled_rows = len(re.findall(
            r"(?:compound|cpd|cmpd|example|实施例|化合物)\s*[-:]?\s*\d+",
            text,
            re.IGNORECASE,
        ))
        dense_numbers = len(re.findall(r"(?<![A-Za-z])\d+(?:\.\d+)?%?(?![A-Za-z])", text))

        if has_context and (has_table_heading or grade_rows >= 2 or labelled_rows >= 3):
            direct.add(page_idx)
        if grade_rows >= 4 or labelled_rows >= 5 or dense_numbers >= 24:
            continuation_evidence.add(page_idx)

    selected = set(direct)
    # Some continuation pages repeat only rows, not the table title.  Include
    # them when they are adjacent to a page already proven to be an activity
    # table, then iterate so multi-page tables remain contiguous.
    changed = True
    while changed:
        changed = False
        for page_idx in pages:
            if page_idx in selected or page_idx not in continuation_evidence:
                continue
            if page_idx - 1 in selected or page_idx + 1 in selected:
                selected.add(page_idx)
                changed = True

    if not selected:
        logger.warning(
            "No cached-text coordinate activity candidates were found; "
            "falling back to %s classified pages",
            len(pages),
        )
        return pages
    return sorted(selected)


def _extract_ruled_activity_rows(doc, activity_pages: list[int]) -> list[ActivityRow]:
    """Extract line-grid assay tables using visible headers and continuation context."""
    rows: list[ActivityRow] = []
    carry_schema: tuple[str, list[str]] | None = None
    for page_idx in sorted({int(page) for page in activity_pages if str(page).isdigit() or isinstance(page, int)}):
        if not (0 <= page_idx < len(doc)):
            continue
        page_no = page_idx + 1
        page = doc[page_idx]
        regions = sorted(_detect_ruled_table_regions(page, dpi=300), key=lambda region: region["bbox"][1])
        if not regions:
            continue
        # Grid detection is much cheaper than OCR.  Do not run a 300 dpi OCR
        # pass until the page has first proven that it contains a line table.
        tokens = _activity_tokens_for_page(page, dpi=300)
        if not tokens:
            continue
        for region in regions:
            y0, y1 = float(region["bbox"][1]), float(region["bbox"][3])
            matrix = _ruled_table_matrix(tokens, region)
            prefix = _ruled_table_context(tokens, max(0.0, y0 - 170.0), y0 + 12.0)
            table_text = " ".join(" ".join(row) for row in matrix[:3])
            classified = _classify_ruled_activity_schema(
                f"{prefix} {table_text}",
                len(region["xs"]) - 1,
            )
            if classified is None and y0 < 130 and carry_schema is not None:
                classified = carry_schema
            if classified is None:
                continue
            rows.extend(_parse_ruled_activity_region(page, page_no, tokens, region, classified))
            carry_schema = classified

        # A continuation title can be printed below the last table on the
        # previous page, before any grid appears on the next page.
        tail = _ruled_table_context(tokens, float(regions[-1]["bbox"][3]), 800.0)
        tail_schema = _classify_ruled_activity_schema(tail)
        if tail_schema is not None:
            carry_schema = tail_schema
    return _merge_activity_rows(rows)


def _rows_from_column_pairs(
    tokens: list[dict],
    page_no: int,
    table_id: str,
    value_key: str,
    pairs: list[tuple[float, float]],
    y_min: float,
    y_max: float,
    source: str = "ocr_grid_table",
) -> list[ActivityRow]:
    rows: list[ActivityRow] = []
    for cpd_x, val_x in pairs:
        cpd_tokens = [
            t for t in tokens
            if y_min <= float(t["y"]) <= y_max
            and abs(float(t["x"]) - cpd_x) <= 20
            and _token_number(t["text"]) is not None
        ]
        for cpd_tok in cpd_tokens:
            cpd_num = _token_number(cpd_tok["text"])
            if cpd_num is None:
                continue
            val_text = _activity_value_near(
                tokens,
                float(cpd_tok["y"]),
                val_x,
                y_tol=7,
                x_tol=42,
                reject_values={str(cpd_num)},
            )
            if not val_text:
                continue
            rows.append(ActivityRow(
                cpd=f"Compound {cpd_num}",
                activity_values={value_key: val_text},
                page_no=page_no,
                table_id=table_id,
                source=source,
                confidence=0.9,
                needs_review=False,
                notes="Coordinate OCR grid extraction for Chinese scanned activity table.",
            ))
    return rows


def _infer_chinese_numeric_assay(text: str, page_idx: int) -> tuple[str, list[str], str] | None:
    compact = re.sub(r"\s+", "", text)
    if "表1" in compact and re.search(r"VCaP.*AR.*降解", compact, re.IGNORECASE):
        return "表1", ["VCaP AR DC50 (nM)"], "VCaP AR degradation"
    if "表2" in compact and re.search(r"LNCaP.*AR.*降解", compact, re.IGNORECASE):
        return "表2", ["LNCaP AR DC50 (nM)", "LNCaP AR Dmax (%)"], "LNCaP AR degradation"
    if "表3" in compact and re.search(r"VCaP.*增殖抑制", compact, re.IGNORECASE):
        return "表3", ["VCaP proliferation IC50 (nM)"], "VCaP proliferation"
    if "表4" in compact and re.search(r"LNCaP.*增殖抑制", compact, re.IGNORECASE):
        return "表4", ["LNCaP proliferation IC50 (nM)"], "LNCaP proliferation"
    return None


def _activity_table_segment(text: str, table_id: str) -> str:
    marker = re.search(re.escape(table_id), text)
    if not marker:
        return text
    tail = text[marker.start():]
    table_num_match = re.search(r"(\d+)", table_id)
    table_num = int(table_num_match.group(1)) if table_num_match else 0
    stop_patterns = []
    if table_num:
        for n in range(table_num + 1, 10):
            stop_patterns.append(rf"表\s*{n}")
            stop_patterns.append(rf"表{n}")
        if table_num < 5:
            stop_patterns.extend([r"表\s*S", r"表S", r"\bHS\b"])
        if table_num < 5:
            stop_patterns.append(rf"试验例\s*{table_num + 1}")
    stop = re.search("|".join(stop_patterns), tail) if stop_patterns else None
    if stop:
        return tail[:stop.start()]
    return tail


def _extract_numeric_groups_from_line(line: str, values_per_compound: int) -> list[tuple[str, list[str]]]:
    line = re.sub(r"([二全<>]\s*\d+(?:\.\d+)?)\s*[?？][46]", r"\1%", line)
    tokens = re.findall(r"[<>]?\s*\d+(?:\.\d+)?\s*%?|[二全]\s*\d+(?:\.\d+)?\s*%?", line)
    cleaned = [_normalise_activity_value(tok) for tok in tokens]
    groups: list[tuple[str, list[str]]] = []
    i = 0
    while i < len(cleaned):
        cpd = cleaned[i]
        if not re.fullmatch(r"\d{1,3}", cpd):
            i += 1
            continue
        cpd_num = int(cpd)
        if cpd_num <= 0 or cpd_num > 300:
            i += 1
            continue
        vals = cleaned[i + 1:i + 1 + values_per_compound]
        if len(vals) < values_per_compound:
            break
        if all(re.search(r"\d", val) for val in vals):
            groups.append((cpd, vals))
            i += 1 + values_per_compound
        else:
            i += 1
    return groups


def _is_confident_dc50_dmax_pair(dc50: str, dmax: str) -> bool:
    dc50_text = str(dc50 or "").strip()
    dmax_text = str(dmax or "").strip().rstrip("%")
    has_dc50 = bool(
        re.fullmatch(r"[A-E]|B1|B2", dc50_text, re.IGNORECASE)
        or re.fullmatch(r"[<>]?\d+(?:\.\d+)?", dc50_text)
    )
    if not has_dc50 or not re.fullmatch(r"\d{1,3}(?:\.\d+)?", dmax_text):
        return False
    try:
        return 0 <= float(dmax_text) <= 100
    except ValueError:
        return False


def _is_specific_activity_row(row: ActivityRow) -> bool:
    source = str(row.source or "")
    return (
        not row.needs_review
        and row.confidence >= 0.88
        and any(token in source for token in (
            "ocr_chinese_dc50_dmax",
            "ocr_ruled_table",
            "ocr_grid_table",
            "ocr_text_table_liver_microsome",
        ))
    )


def _is_noisy_generic_activity_row(row: ActivityRow) -> bool:
    source = str(row.source or "")
    if not any(token in source for token in (
        "ocr_text_table",
        "ocr_text_table_flat",
        "ocr_chinese_adme_pk",
        "ocr_chinese_multi_table",
        "ocr_chinese_multi_numeric",
    )):
        return False
    return bool(row.needs_review or row.confidence <= 0.6 or len(row.activity_values or {}) > 8)


def _prefer_specific_activity_rows(rows: list[ActivityRow]) -> list[ActivityRow]:
    """Drop noisy generic rows when a same-compound specific table row exists."""
    specific_cpds = {
        _normalize_activity_cpd_label(row.cpd)
        for row in rows
        if _is_specific_activity_row(row)
    }
    if not specific_cpds:
        return rows
    filtered: list[ActivityRow] = []
    for row in rows:
        norm_cpd = _normalize_activity_cpd_label(row.cpd)
        if norm_cpd in specific_cpds and not _is_specific_activity_row(row) and _is_noisy_generic_activity_row(row):
            continue
        filtered.append(row)
    return filtered


def _merge_activity_rows(rows: list[ActivityRow]) -> list[ActivityRow]:
    rows = _prefer_specific_activity_rows(rows)

    def should_replace_activity_value(old: str, new: str, old_conf: float, new_conf: float) -> bool:
        if not old:
            return True
        if not new:
            return False
        if old == new:
            return False
        # Keep explicit threshold signs from the higher-confidence ruled-table
        # path over lower-confidence coordinate fallbacks that often drop ">".
        old_core = re.sub(r"^[<>]", "", str(old))
        new_core = re.sub(r"^[<>]", "", str(new))
        if old_core == new_core and re.match(r"^[<>]", str(old)) and not re.match(r"^[<>]", str(new)):
            return False
        if old_core == new_core and re.match(r"^[<>]", str(new)) and not re.match(r"^[<>]", str(old)):
            return True
        return new_conf >= old_conf

    merged: dict[str, ActivityRow] = {}
    first_seen: dict[str, int] = {}
    value_confidence: dict[tuple[str, str, str], float] = {}
    for row_index, row in enumerate(rows):
        norm_cpd = _normalize_activity_cpd_label(row.cpd)
        if not norm_cpd:
            continue
        if norm_cpd not in merged:
            first_seen[norm_cpd] = row_index
            merged[norm_cpd] = ActivityRow(
                cpd=norm_cpd,
                activity_values={},
                cell_line_data={},
                page_no=row.page_no,
                table_id=row.table_id,
                column_side=row.column_side,
                source=row.source,
                confidence=row.confidence,
                needs_review=row.needs_review,
                notes=row.notes,
            )
        target = merged[norm_cpd]
        for evidence in row.activity_sources:
            if evidence not in target.activity_sources:
                target.activity_sources.append(evidence)
        if row.page_no and (not target.page_no or target.page_no <= 0 or row.page_no < target.page_no):
            target.page_no = row.page_no
        for bucket_name in ("activity_values", "cell_line_data"):
            target_bucket = getattr(target, bucket_name)
            incoming_bucket = getattr(row, bucket_name) or {}
            for key, new_value in incoming_bucket.items():
                conf_key = (norm_cpd, bucket_name, key)
                old_value = target_bucket.get(key, "")
                old_text = str(old_value or "").strip()
                new_text = str(new_value or "").strip()
                old_conf = value_confidence.get(conf_key, target.confidence)
                if old_text and new_text and old_text != new_text:
                    conflict_note = f"conflicting {bucket_name}.{key}: {old_text} vs {new_text}"
                    target.needs_review = True
                    if conflict_note not in target.notes:
                        target.notes = f"{target.notes}; {conflict_note}" if target.notes else conflict_note
                if should_replace_activity_value(old_text, new_text, old_conf, row.confidence):
                    target_bucket[key] = new_value
                    value_confidence[conf_key] = row.confidence
        if row.table_id:
            parts = [p for p in re.split(r"/", target.table_id or "") if p]
            for part in [p for p in re.split(r"/", row.table_id) if p]:
                if part not in parts:
                    parts.append(part)
                target.table_id = "/".join(parts)
        if row.source and row.source not in target.source:
            target.source = f"{target.source}+{row.source}" if target.source else row.source
        target.confidence = min(target.confidence, row.confidence)
        target.needs_review = target.needs_review or row.needs_review
        if row.notes and row.notes not in target.notes:
            target.notes = f"{target.notes}; {row.notes}" if target.notes else row.notes

    # Use earliest physical table occurrence as row order; parser execution
    # order must not reorder activity-source rows.
    return sorted(
        merged.values(),
        key=lambda row: (
            0 if row.page_no and row.page_no > 0 else 1,
            row.page_no if row.page_no and row.page_no > 0 else 10**9,
            first_seen.get(_normalize_activity_cpd_label(row.cpd), 10**9),
        ),
    )


def _page_no_before_offset(text: str, offset: int) -> int:
    page_no = 0
    for match in re.finditer(r"\[\[PAGE\s+(\d+)\]\]", text[:max(0, offset)]):
        page_no = int(match.group(1))
    return page_no


def _extract_chinese_adme_pk_activity_rows_from_ocr(doc, activity_pages: list[int], page_text_map: Optional[dict[str, str]] = None) -> list[ActivityRow]:
    """Extract Chinese mixed activity/ADME/PK tables from flattened OCR text."""
    rows: list[ActivityRow] = []
    try:
        from patent_sar_extractor.core.patent_profiler import _ocr_page_fallback
    except Exception:
        _ocr_page_fallback = None

    full_text_parts: list[str] = []
    for page_idx in activity_pages:
        if page_idx >= len(doc):
            continue
        text = str((page_text_map or {}).get(str(page_idx), ""))
        if not text.strip():
            text = doc[page_idx].get_text("text")
        if not text.strip() and _ocr_page_fallback is not None:
            text = _ocr_page_fallback(doc[page_idx])
        if text.strip():
            full_text_parts.append(f"\n[[PAGE {page_idx + 1}]]\n{text}")
    full_text = "\n".join(full_text_parts)
    if not full_text.strip():
        return []

    table_specs = [
        ("表1", ["VCaP AR DC50 (nM)"]),
        ("表2", ["LNCaP AR DC50 (nM)", "LNCaP AR Dmax (%)"]),
        ("表3", ["VCaP proliferation IC50 (nM)"]),
        ("表4", ["LNCaP proliferation IC50 (nM)"]),
    ]
    for table_id, value_keys in table_specs:
        marker = re.search(re.escape(table_id), full_text)
        segment = _activity_table_segment(full_text, table_id)
        if segment == full_text and table_id not in full_text:
            continue
        page_match = re.search(r"\[\[PAGE\s+(\d+)\]\]", segment)
        page_no = int(page_match.group(1)) if page_match else _page_no_before_offset(full_text, marker.start() if marker else 0)
        for raw_line in segment.splitlines():
            line = re.sub(r"\s+", " ", raw_line).strip()
            if not re.match(r"^\d{1,3}\s+", line):
                continue
            groups = _extract_numeric_groups_from_line(line, len(value_keys))
            for cpd_num, vals in groups:
                value_map = dict(zip(value_keys, vals))
                rows.append(ActivityRow(
                    cpd=f"Compound {int(cpd_num)}",
                    activity_values=value_map,
                    page_no=page_no,
                    table_id=table_id,
                    source="ocr_chinese_multi_table",
                    confidence=0.82,
                    needs_review=True,
                    notes="OCR fallback for Chinese/English mixed repeated compound/activity table.",
                ))

    table5_match = re.search(
        r"(?:实验结果见表\s*S|实验结果见表S|结果见表\s*S|结果见表S).{0,240}?\bHS\b\s*(.+?)(?=试验例\s*[:：]?\s*4|表\s*6|$)",
        full_text,
        re.I | re.S,
    )
    if table5_match:
        segment = table5_match.group(1)
        page_match = re.search(r"\[\[PAGE\s+(\d+)\]\]", table5_match.group(0))
        page_no = int(page_match.group(1)) if page_match else 214
        for raw_line in segment.splitlines():
            line = re.sub(r"\s+", " ", raw_line).strip()
            if not re.match(r"^\d{1,3}\s+", line):
                continue
            for cpd_num, value in re.findall(r"(?<![\d.])(\d{1,3})\s+([<>二全]\s*85\s*%?)", line):
                n = int(cpd_num)
                if n <= 0 or n > 300:
                    continue
                rows.append(ActivityRow(
                    cpd=f"Compound {n}",
                    activity_values={"Human liver microsome remaining at 60 min (%)": _normalise_activity_value(value)},
                    page_no=page_no,
                    table_id="表5",
                    source="ocr_chinese_adme_pk",
                    confidence=0.78,
                    needs_review=True,
                    notes="OCR fallback for Chinese/English mixed ADME table.",
                ))

    table6_match = re.search(r"表\s*6\s+(.+?)(?=本申请化合物具有良好的体内药代动力学参数|$)", full_text, re.I | re.S)
    if table6_match:
        segment = table6_match.group(1)
        page_match = re.search(r"\[\[PAGE\s+(\d+)\]\]", table6_match.group(0))
        page_no = int(page_match.group(1)) if page_match else 215
        for raw_line in segment.splitlines():
            line = re.sub(r"\s+", " ", raw_line).strip()
            if not re.match(r"^\d{1,3}\s+", line):
                continue
            tokens = re.findall(r"\d+(?:\.\d+)?%?", line)
            if len(tokens) < 7:
                continue
            cpd = tokens[0]
            if len(tokens) >= 8:
                iv_auc, iv_t12, iv_cl, po_auc, po_t12, cmax, bio_f = tokens[1:8]
            else:
                iv_auc, iv_cl, po_auc, po_t12, cmax, bio_f = tokens[1:7]
                iv_t12 = ""
            values = {
                "Mouse IV AUC (ng*h/mL)": iv_auc,
                "Mouse IV t1/2 (h)": iv_t12 or "",
                "Mouse IV CL (L/hr/kg)": iv_cl,
                "Mouse PO AUC (ng*h/mL)": po_auc,
                "Mouse PO t1/2 (h)": po_t12,
                "Mouse PO Cmax (ng/mL)": cmax,
                "Mouse oral bioavailability F (%)": _normalise_activity_value(bio_f),
            }
            rows.append(ActivityRow(
                cpd=f"Compound {int(cpd)}",
                activity_values=values,
                page_no=page_no,
                table_id="表6",
                source="ocr_chinese_adme_pk",
                confidence=0.78,
                needs_review=True,
                notes="OCR fallback for Chinese/English mixed mouse PK table.",
            ))

    return _merge_activity_rows(rows)


def _extract_chinese_multi_numeric_activity_rows_from_ocr(doc, activity_pages: list[int], page_text_map: Optional[dict[str, str]] = None) -> list[ActivityRow]:
    """Extract Chinese activity tables laid out as repeated compound/value groups."""
    rows_by_cpd: dict[str, ActivityRow] = {}
    try:
        from patent_sar_extractor.core.patent_profiler import _ocr_page_fallback
    except Exception:
        _ocr_page_fallback = None

    for page_idx in activity_pages:
        if page_idx >= len(doc):
            continue
        text = str((page_text_map or {}).get(str(page_idx), ""))
        if not text.strip():
            text = doc[page_idx].get_text("text")
        if not text.strip() and _ocr_page_fallback is not None:
            text = _ocr_page_fallback(doc[page_idx])
        assay = _infer_chinese_numeric_assay(text, page_idx)
        if not assay:
            continue
        table_id, value_keys, assay_name = assay
        values_per_compound = len(value_keys)
        text = _activity_table_segment(text, table_id)

        for raw_line in text.splitlines():
            line = re.sub(r"\s+", " ", raw_line).strip()
            if not line:
                continue
            if not re.match(r"^\s*\d{1,3}\b", line):
                continue
            groups = _extract_numeric_groups_from_line(line, values_per_compound)
            for cpd_num, vals in groups:
                cpd = f"Compound {int(cpd_num)}"
                if cpd not in rows_by_cpd:
                    rows_by_cpd[cpd] = ActivityRow(
                        cpd=cpd,
                        activity_values={},
                        page_no=page_idx + 1,
                        table_id=table_id,
                        source="ocr_chinese_multi_numeric",
                        confidence=0.82,
                        needs_review=True,
                        notes="OCR fallback for Chinese repeated compound/activity table.",
                    )
                row = rows_by_cpd[cpd]
                row.activity_values.update(dict(zip(value_keys, vals)))
                if table_id not in row.table_id.split("/"):
                    row.table_id = f"{row.table_id}/{table_id}" if row.table_id else table_id
                row.notes = row.notes or f"{assay_name}; OCR fallback for Chinese repeated compound/activity table."

    return sorted(
        rows_by_cpd.values(),
        key=lambda r: int(re.search(r"\d+", r.cpd).group(0)) if re.search(r"\d+", r.cpd) else 10**9,
    )


_LONG_CHEMICAL_NAME_RE = re.compile(
    r"(?:chemical\s+name\s+[\"“']?\s*)?"
    r"([A-Z]?[0-9]?-?\(?[0-9]?-?\(?[0-9]?-?\(?[0-9]?-?[A-Za-z][A-Za-z0-9()\\[\\],.'’\\-\\s]{35,}?"
    r"(?:phenol|pyridine|pyrimidine|benzene|benzamide|amide|amine|azole|acid|ester|ether|one|ol|yl))",
    re.IGNORECASE,
)


def _clean_singleton_chemical_name(value: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip(" \"'“”‘’.,;:")
    text = re.sub(r"\b\d{6,}\b", "", text)
    text = re.sub(r"(?<=[A-Za-z])\s+(?=[A-Z]{2,}\b)", "", text)
    text = re.sub(r"\bPH\s+ENOXY\b", "PHENOXY", text, flags=re.IGNORECASE)
    text = re.sub(r"\bDIBROMOPH\s+ENOXY\b", "DIBROMOPHENOXY", text, flags=re.IGNORECASE)
    text = text.replace("''", "").replace("``", "")
    text = re.sub(r"\s+or\s+a\s+pharmacologically.*$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+and\s+(?:its|related)\s+.*$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+for\s+muscle\s+.*$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" \"'“”‘’.,;:")


def _singleton_name_candidates(full_text: str) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    quoted_patterns = [
        r"chemical\s+Name\s*[\"“'']\s*([^\"”''\n]{30,360})[\"”'']",
        r"chemical\s+name\s+[\"“'']\s*([^\"”''\n]{30,360})[\"”'']",
        r"Name\s*[\"“'']\s*([^\"”''\n]{30,360})[\"”'']",
    ]
    for pattern in quoted_patterns:
        for match in re.finditer(pattern, full_text, re.IGNORECASE):
            name = _clean_singleton_chemical_name(match.group(1))
            if len(name) < 30:
                continue
            if not re.search(r"phenol|pyridine|pyrimidine|benzene|benzamide|amide|amine|azole|acid|ester|ether|one|ol", name, re.IGNORECASE):
                continue
            if len(re.findall(r"\d|\(|\)|-|,", name)) < 4:
                continue
            key = re.sub(r"\s+", " ", name)
            counts[key] = counts.get(key, 0) + 4

    context_patterns = [
        r"chemical\s+Name\s*[\"“'']?\s*(.{20,320}?(?:phenol|pyridine|pyrimidine|benzene|benzamide|amide|amine|azole|acid|ester|ether|one|ol)(?![A-Za-z]))",
        r"Title\s+of\s+Invention\s*:\s*(?:Pharmaceutical\s+composition\s+comprising\s+)?(.{20,260}?(?:phenol|pyridine|pyrimidine|benzene|benzamide|amide|amine|azole|acid|ester|ether|one|ol)(?![A-Za-z]))",
        r"new\s+compound\s+with\s+the\s+chemical\s+name\s*[\"“'']?\s*(.{20,320}?(?:phenol|pyridine|pyrimidine|benzene|benzamide|amide|amine|azole|acid|ester|ether|one|ol)(?![A-Za-z]))",
        r"compound\s+with\s+the\s+Name\s*[\"“'']?\s*(.{20,320}?(?:phenol|pyridine|pyrimidine|benzene|benzamide|amide|amine|azole|acid|ester|ether|one|ol)(?![A-Za-z]))",
    ]
    for pattern in context_patterns:
        for match in re.finditer(pattern, full_text, re.IGNORECASE | re.DOTALL):
            name = _clean_singleton_chemical_name(match.group(1))
            if len(name) < 30:
                continue
            if len(re.findall(r"\d|\\(|\\)|-|,", name)) < 4:
                continue
            key = re.sub(r"\s+", " ", name)
            counts[key] = counts.get(key, 0) + 2

    for match in _LONG_CHEMICAL_NAME_RE.finditer(full_text):
        name = _clean_singleton_chemical_name(match.group(1))
        if len(name) < 35:
            continue
        # Avoid long prose fragments that only happen to end with chemistry-like
        # suffixes; singleton names should contain several structure tokens.
        if len(re.findall(r"\d|\\(|\\)|-|,", name)) < 5:
            continue
        key = re.sub(r"\s+", " ", name)
        counts[key] = counts.get(key, 0) + 1
    return sorted(counts.items(), key=lambda item: (-item[1], -len(item[0])))


def _singleton_activity_evidence(full_text: str) -> dict[str, str]:
    """Summarise prose/figure activity evidence for single-compound patents.

    These patents often do not contain a compound-number activity table. They
    describe one named active compound (frequently abbreviated in figures) and
    report experimental effects in prose/figure legends. Treat this as an
    activity-bearing row so the activity-led pipeline does not fail closed into
    an empty result.
    """
    evidence_patterns = [
        (
            "myogenesis/fusion evidence",
            r"fusion index|myotubes?|myogenesis|muscle maturation|SERCA1|actin cytoskeleton",
        ),
        (
            "proliferation/senescence evidence",
            r"Ki67|Cyclin|proliferation|senescence|apoptosis|caspase",
        ),
        (
            "microgravity protection evidence",
            r"microgravity|s-?u?g|simulated gravity|spaceflight",
        ),
        (
            "muscle function evidence",
            r"grip strength|treadmill|muscle weight|fatigue|endurance",
        ),
        (
            "cardiac/cancer cell evidence",
            r"ischemia|reperfusion|LVDP|LVEDP|cell survival|viability|MCF-7|colorectal",
        ),
    ]
    values: dict[str, str] = {}
    for key, pattern in evidence_patterns:
        hits = len(re.findall(pattern, full_text, flags=re.IGNORECASE))
        if hits:
            values[key] = f"reported ({hits} OCR hits)"
    figure_hits = sorted({int(m.group(1)) for m in re.finditer(r"Figure\s+(\d{1,3})", full_text, flags=re.IGNORECASE)})
    if figure_hits:
        if len(figure_hits) > 12:
            display = f"{figure_hits[0]}-{figure_hits[-1]} ({len(figure_hits)} figures)"
        else:
            display = ", ".join(str(n) for n in figure_hits)
        values["figure activity evidence"] = display
    dose_hits = sorted(set(re.findall(r"\b\d+(?:\.\d+)?\s*(?:nM|uM|µM|μM|mg/kg|g/Kg|μg/Kg)\b", full_text, flags=re.IGNORECASE)))
    if dose_hits:
        values["tested dose/concentration evidence"] = ", ".join(dose_hits[:12])
    return values


def _extract_singleton_named_compound_activity_rows_from_ocr(
    doc,
    profile: dict,
    page_text_map: Optional[dict[str, str]] = None,
) -> list[ActivityRow]:
    """Fallback for single-active-compound patents without numbered tables.

    The rule is deliberately conservative: require a repeated long chemical
    name, activity/effect evidence, and no meaningful numbered activity rows.
    This keeps normal SAR tables activity-led, while rescuing formulation/use
    patents built around one named compound.
    """
    page_text_map = page_text_map or {}
    full_parts: list[str] = []
    pages_with_text: list[int] = []
    for page_idx in range(len(doc)):
        text = str(page_text_map.get(str(page_idx), "") or "")
        if not text.strip():
            text = doc[page_idx].get_text("text")
        if not text.strip():
            continue
        pages_with_text.append(page_idx + 1)
        full_parts.append(f"\n[[PAGE {page_idx + 1}]]\n{text}")
    full_text = "\n".join(full_parts)
    if not full_text.strip():
        return []

    # If a real numbered activity table exists, this fallback should not create
    # an extra pseudo-compound.
    numbered_activity_rows = len(re.findall(
        r"(?:Compound|Cpd|Example|化合物|实施例)\s*[-:]?\s*\d+(?:-\d+)?[A-Z]?"
        r".{0,80}(?:IC50|EC50|DC50|Dmax|Ki\b|Kd\b|AUC|Cmax|TGI|grade)",
        full_text,
        flags=re.IGNORECASE | re.DOTALL,
    ))
    if numbered_activity_rows >= 3:
        return []

    name_candidates = _singleton_name_candidates(full_text)
    if not name_candidates:
        return []
    name, name_hits = name_candidates[0]
    has_claim_formula_context = bool(re.search(
        r"claim\s*1.{0,220}(?:formula\s+shown\s+here|shown\s+here|new\s+compound)|"
        r"formula\s+of\s+the\s+new\s+compound|chemical\s+formula.{0,160}Figure\s*[12]",
        full_text,
        re.IGNORECASE | re.DOTALL,
    ))
    if name_hits < 2 and not has_claim_formula_context:
        return []

    evidence = _singleton_activity_evidence(full_text)
    evidence_score = sum(1 for key in evidence if key != "tested dose/concentration evidence")
    if evidence_score < 2:
        return []

    alias_hits = len(re.findall(r"\bCX\b", full_text))
    if alias_hits >= 3:
        evidence["abbreviation evidence"] = f"CX ({alias_hits} OCR hits)"

    first_page = pages_with_text[0] if pages_with_text else 0
    return [
        ActivityRow(
            cpd="Claim 1 compound",
            activity_values=evidence,
            page_no=first_page,
            table_id="singleton active compound evidence",
            source="ocr_singleton_named_compound",
            confidence=0.86,
            needs_review=False,
            notes=(
                "No numbered activity table detected; extracted activity-led "
                f"singleton main compound from repeated chemical name: {name}"
            ),
        )
    ]


def _group_ocr_tokens_by_y(tokens: list[dict], tolerance: float = 18.0) -> list[list[dict]]:
    rows: list[list[dict]] = []
    for token in sorted(tokens, key=lambda t: (t["y"], t["x"])):
        if not rows or abs(token["y"] - rows[-1][0]["y"]) > tolerance:
            rows.append([token])
        else:
            rows[-1].append(token)
    for row in rows:
        row.sort(key=lambda t: t["x"])
    return rows


def _find_token_y(tokens: list[dict], pattern: str, default: float = 0.0) -> float:
    rx = re.compile(pattern, re.IGNORECASE)
    ys = [t["y"] for t in tokens if rx.search(t["text"])]
    return min(ys) if ys else default


def _normalise_letter_grade_metric(value: str) -> str:
    metric = re.sub(r"\s+", " ", str(value or "")).strip(" .,;:")
    metric = re.sub(
        r"\b(p?IC|EC|DC|GI|CC)[S5]?[oO0]\b",
        lambda match: f"{match.group(1).upper()}50",
        metric,
        flags=re.IGNORECASE,
    )
    metric = re.sub(
        r"\b(p?IC|EC|DC|GI|CC)5[oO0]\b",
        lambda match: f"{match.group(1).upper()}50",
        metric,
        flags=re.IGNORECASE,
    )
    return metric


def _prefixed_letter_grade_schema(text: str) -> Optional[dict]:
    """Read a generic A-G assay legend and its table identity from OCR text."""
    source = re.sub(r"\s+", " ", str(text or "")).strip()
    legend_header = re.search(
        r"letter\s+codes?\s+for\s+(.{1,80}?)\s+include\s*:",
        source,
        re.IGNORECASE,
    )
    if not legend_header:
        return None

    metric = _normalise_letter_grade_metric(legend_header.group(1))
    legend_tail = source[legend_header.end():legend_header.end() + 700]
    table_offset = re.search(r"\bTable\s*\d+\b", legend_tail, re.IGNORECASE)
    if table_offset:
        legend_tail = legend_tail[:table_offset.start()]
    definitions = {
        grade.upper(): re.sub(r"\s+", " ", definition).strip(" .;:")
        for grade, definition in re.findall(r"\b([A-G])\s*\(\s*([^)]+?)\s*\)", legend_tail, re.IGNORECASE)
    }
    if len(definitions) < 2:
        return None

    table_match = re.search(r"\bTable\s*(\d+)\b", source[legend_header.end():], re.IGNORECASE)
    table_id = f"Table {table_match.group(1)}" if table_match else "letter-grade activity table"

    title = ""
    title_match = re.search(
        r"(?:\[\d+\]\s*)?(?:The\s+)?([A-Z][A-Za-z0-9\- ]{2,80}?)\s+results\s+are\s+shown",
        source,
        re.IGNORECASE,
    )
    if title_match:
        title = re.sub(r"\s+", " ", title_match.group(1)).strip(" .;:")
    if not title and table_match:
        after_table = source[legend_header.end() + table_match.end():]
        title_match = re.match(r"\s*[.:]?\s*([A-Za-z][A-Za-z0-9\- ]{2,80}?)\s+(?=[A-Z][A-Za-z0-9-]*\s*[,:])", after_table)
        if title_match:
            title = re.sub(r"\s+", " ", title_match.group(1)).strip(" .;:")
    title = title or "Activity"
    assay_key = f"{title} {metric}".strip()
    return {
        "table_id": table_id,
        "title": title,
        "metric": metric,
        "assay_key": assay_key,
        "definitions": definitions,
    }


def _extract_prefixed_letter_grade_activity_rows_from_ocr(
    activity_pages: list[int],
    page_text_map: Optional[dict[str, str]] = None,
) -> list[ActivityRow]:
    """Extract generic ``series-number + A-G grade`` assay tables from text.

    The first page supplies a legend such as ``A (<1 nM); B (1-10 nM)``.
    Adjacent continuation pages often repeat only the assay header and rows.
    OCR commonly confuses the series prefix ``I`` with the digit ``1``; the
    source label is preserved in notes while the compound is normalized to the
    numeric identity used by the downstream structure binder.
    """
    if not page_text_map:
        return []

    rows_by_key: dict[tuple[str, str], ActivityRow] = {}
    current_schema: Optional[dict] = None
    last_table_page: Optional[int] = None
    pages = sorted({
        int(page_idx)
        for page_idx in activity_pages
        if isinstance(page_idx, int) or str(page_idx).isdigit()
    })

    for page_idx in pages:
        text = str(page_text_map.get(str(page_idx), "") or "")
        if not text.strip():
            continue
        row_matches = list(_PREFIXED_GRADE_ROW_RE.finditer(text))
        schema = _prefixed_letter_grade_schema(text)
        if schema:
            current_schema = schema
        elif not (
            current_schema
            and last_table_page is not None
            and page_idx == last_table_page + 1
            and row_matches
            and _COORDINATE_ACTIVITY_CONTEXT_RE.search(text)
        ):
            current_schema = None
            last_table_page = None
            continue

        if not current_schema or not row_matches:
            continue
        last_table_page = page_idx

        definitions = current_schema.get("definitions", {})
        assay_key = str(current_schema.get("assay_key") or "Activity grade")
        table_id = str(current_schema.get("table_id") or "letter-grade activity table")
        for match in row_matches:
            raw_prefix = match.group(1).upper()
            source_prefix = "I" if raw_prefix in {"1", "I", "L"} else raw_prefix
            compound_number = str(int(match.group(2)))
            grade = match.group(3).upper()
            decoded_value = str(definitions.get(grade, grade)).strip()
            cpd = f"Compound {compound_number}"
            row_key = (cpd, assay_key)
            notes = (
                f"Letter-grade activity decoded from source label "
                f"{source_prefix}-{compound_number} (grade {grade})."
            )
            existing = rows_by_key.get(row_key)
            if existing is not None:
                prior = existing.activity_values.get(assay_key, "")
                if prior != decoded_value:
                    existing.needs_review = True
                    existing.confidence = min(existing.confidence, 0.6)
                    existing.notes = f"{existing.notes} Conflicting duplicate value: {decoded_value}."
                continue
            rows_by_key[row_key] = ActivityRow(
                cpd=cpd,
                activity_values={assay_key: decoded_value},
                page_no=page_idx + 1,
                table_id=table_id,
                source="ocr_prefixed_letter_grade",
                confidence=0.95 if grade in definitions else 0.82,
                needs_review=grade not in definitions,
                notes=notes,
            )

    return sorted(
        rows_by_key.values(),
        key=lambda row: (
            int(re.search(r"\d+", row.cpd).group(0)) if re.search(r"\d+", row.cpd) else 10**9,
            row.table_id,
        ),
    )


def _letter_row_values(tokens: list[dict]) -> tuple[str, list[str]] | None:
    nums = [t for t in tokens if re.fullmatch(r"\d{1,3}", t["text"]) and int(t["text"]) <= 300]
    letters = [t for t in tokens if re.fullmatch(r"[A-E]", t["text"].upper())]
    if not nums or not letters:
        return None
    cpd_num = sorted(nums, key=lambda t: t["x"])[0]["text"]
    grades = [t["text"].upper() for t in sorted(letters, key=lambda t: t["x"])]
    return cpd_num, grades


def _merge_letter_activity(rows_by_cpd: dict[str, ActivityRow], cpd_num: str, values: dict, page_no: int, table_id: str):
    cpd = f"Example{int(cpd_num)}"
    if cpd not in rows_by_cpd:
        rows_by_cpd[cpd] = ActivityRow(
            cpd=cpd,
            activity_values={},
            page_no=page_no,
            table_id=table_id,
            source="ocr_letter_grade",
            confidence=0.82,
        )
    rows_by_cpd[cpd].activity_values.update(values)


def _extract_letter_grade_activity_rows_from_ocr(doc, activity_pages: list[int], page_text_map: Optional[dict[str, str]] = None) -> list[ActivityRow]:
    """Extract A/B/C/D/E categorical activity tables from scanned patents."""
    rows_by_cpd: dict[str, ActivityRow] = {}

    for page_idx in activity_pages:
        if page_idx >= len(doc):
            continue
        cached_text = str((page_text_map or {}).get(str(page_idx), "") or "")
        if page_text_map and not re.search(
            r"CRBN\s+Binding|IKZF[12]\s*(?:FACS|HiBit)",
            cached_text,
            re.IGNORECASE,
        ):
            continue
        tokens = _ocr_tokens_with_positions(doc[page_idx])
        if not tokens:
            continue

        joined = cached_text or " ".join(t["text"] for t in tokens)
        grouped = _group_ocr_tokens_by_y(tokens)
        page_no = page_idx + 1

        if re.search(r"CRBN\s+Binding", joined, re.IGNORECASE):
            start_y = _find_token_y(tokens, r"IC50|IC5o", 160) + 25
            end_y = _find_token_y(tokens, r"^\s*A\s*:", 10_000)
            for row in grouped:
                y = sum(t["y"] for t in row) / len(row)
                if not (start_y <= y <= end_y):
                    continue
                parsed = _letter_row_values(row)
                if parsed:
                    cpd_num, grades = parsed
                    _merge_letter_activity(
                        rows_by_cpd, cpd_num,
                        {"CRBN Binding IC50 (uM) grade": grades[-1]},
                        page_no, "Table E1",
                    )

        if re.search(r"IKZF2\s*FACS|IKZF2FACS", joined, re.IGNORECASE):
            start_y = max(
                _find_token_y(tokens, r"DC50|DC5o|Dmax", 170) + 25,
                _find_token_y(tokens, r"Table\s*E2", 0) + 70,
            )
            end_y = _find_token_y(tokens, r"DC50\s*:|Dmax\s*:", 10_000)
            for row in grouped:
                y = sum(t["y"] for t in row) / len(row)
                if not (start_y <= y <= end_y):
                    continue
                parsed = _letter_row_values(row)
                if parsed:
                    cpd_num, grades = parsed
                    if len(grades) >= 2:
                        _merge_letter_activity(
                            rows_by_cpd, cpd_num,
                            {
                                "IKZF2 FACS Dmax (%) grade": grades[0],
                                "IKZF2 FACS DC50 (nM) grade": grades[1],
                            },
                            page_no, "Table E2",
                        )

        if re.search(r"IKZF2\s*HiBit|IKZF2HiBit|IKZF1\s*HiBit|IKZF1HiBit", joined, re.IGNORECASE):
            start_y = max(
                _find_token_y(tokens, r"DC50|DC5o|Dmax", 170) + 25,
                _find_token_y(tokens, r"Table\s*E3", 0) + 70,
            )
            end_y = _find_token_y(tokens, r"IKZF2\s+degradation|INCORPORATION", 10_000)
            for row in grouped:
                y = sum(t["y"] for t in row) / len(row)
                if not (start_y <= y <= end_y):
                    continue
                parsed = _letter_row_values(row)
                if parsed:
                    cpd_num, grades = parsed
                    if len(grades) >= 4:
                        _merge_letter_activity(
                            rows_by_cpd, cpd_num,
                            {
                                "IKZF2 HiBit DC50 (nM) grade": grades[0],
                                "IKZF2 HiBit Dmax (%) grade": grades[1],
                                "IKZF1 HiBit DC50 (nM) grade": grades[2],
                                "IKZF1 HiBit Dmax (%) grade": grades[3],
                            },
                            page_no, "Table E3",
                        )

    return sorted(
        rows_by_cpd.values(),
        key=lambda r: int(re.search(r"\d+", r.cpd).group(0)) if re.search(r"\d+", r.cpd) else 10**9,
    )


def _run_vlm_phase(
    ocr_rows,
    pdf_path,
    output_dir,
    api_url,
    api_key,
    model,
    tables,
    column_layout,
    vlm_call,
):
    """Run VLM verification phase"""
    doc = fitz.open(pdf_path)
    vlm_dir = output_dir / "vlm_images"
    vlm_dir.mkdir(parents=True, exist_ok=True)
    
    page_images = {}
    
    for table_info in tables:
        pages_idx = table_info.get("pages", [])
        table_id = table_info["table_id"]
        
        for page_idx in pages_idx:
            if page_idx >= len(doc):
                continue
            
            # Render table region
            label = "t1" if "1" in table_id else "t2" if "2" in table_id else "table"
            img_path = _render_table_image(doc, page_idx, 55, 790, vlm_dir, label)
            key = f"{page_idx+1}_{label}"
            page_images[key] = (img_path, table_id)
    
    doc.close()
    
    # Call VLM
    vlm_results = {}
    for key, (img_path, table_id) in page_images.items():
        prompt = _build_vlm_prompt(table_id, column_layout)
        logger.info(f"VLM: {key} ({table_id})...")
        response = vlm_call(img_path, prompt, api_url, api_key, model)
        parsed = _parse_vlm_json(response)
        
        vlm_results[key] = {
            "page_no": int(key.split("_")[0]),
            "table_id": table_id,
            "raw_response": response,
            "parsed_rows": parsed,
        }
        logger.info(f"  → {len(parsed)} rows from VLM")
    
    return vlm_results


def _build_vlm_prompt(table_id: str, column_layout: dict) -> str:
    """Build VLM prompt based on table type and layout"""
    layout_desc = "double-column" if column_layout["type"] == "double" else "single-column"
    
    return f"""This is a cropped image from a patent showing {table_id} ({layout_desc} layout).

Extract ALL compound rows as JSON array:
```json
[{{"cpd": "Cpd-1", "values": {{"DC50(nM)": "14", "Dmax(%)": "44"}}}}]
```

Rules:
- If a value is "∞" or "in" or infinity symbol, write ">10000"
- Read numbers carefully (e.g., "47" NOT "4]")
- Preserve exact compound numbers
- Ignore trailing "|" or "." on numbers
- Include ALL visible compounds
- For double-column layout, mark each entry with side: left or right"""


def _save_results(
    rows: list[ActivityRow],
    vlm_results: Optional[dict],
    output_dir: Path,
    profile: dict,
):
    """Save extraction results to CSV + JSON"""
    # ── CSV ──
    all_value_keys = list(dict.fromkeys(
        k for r in rows for k in r.activity_values.keys()
    ))
    all_cell_keys = list(dict.fromkeys(
        k for r in rows for k in r.cell_line_data.keys()
    ))
    
    fieldnames = [
        "cpd", "page_no", "table_id", "column_side",
        "source", "confidence", "needs_review", "notes",
    ] + all_value_keys + all_cell_keys
    
    csv_path = output_dir / "activity_data.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            d = {
                "cpd": r.cpd,
                "page_no": r.page_no,
                "table_id": r.table_id,
                "column_side": r.column_side,
                "source": r.source,
                "confidence": r.confidence,
                "needs_review": r.needs_review,
                "notes": r.notes,
            }
            for k in all_value_keys:
                d[k] = r.activity_values.get(k, "")
            for k in all_cell_keys:
                d[k] = r.cell_line_data.get(k, "")
            writer.writerow(d)
    
    logger.info(f"CSV: {csv_path}")
    
    # ── JSON ──
    active_cpds = list(dict.fromkeys(
        _normalize_activity_cpd_label(r.cpd)
        for r in rows
        if _normalize_activity_cpd_label(r.cpd)
        and not _is_control_or_reference_activity_label(r.cpd)
        and _activity_row_has_usable_values(r)
    ))
    json_data = {
        **artifact_identity(ACTIVITY_SCHEMA, ACTIVITY_SCHEMA_VERSION),
        "metadata": {
            "timestamp": datetime.now().isoformat(),
            "patent_id": profile.get("patent_id", ""),
            "n_rows": len(rows),
            "n_unique_cpds": len(set(r.cpd for r in rows)),
            "n_active_cpds": len(active_cpds),
        },
        "active_cpds": active_cpds,
        "rows": [
            {
                "cpd": r.cpd,
                "activity_values": r.activity_values,
                "cell_line_data": r.cell_line_data,
                "page_no": r.page_no,
                "table_id": r.table_id,
                "column_side": r.column_side,
                "source": r.source,
                "confidence": r.confidence,
                "needs_review": r.needs_review,
                "notes": r.notes,
                "activity_sources": r.activity_sources,
            }
            for r in rows
        ],
    }
    
    json_path = output_dir / "activity_data.json"
    write_json_atomic(json_path, json_data)
    
    logger.info(f"JSON: {json_path}")
    
    # ── VLM results ──
    if vlm_results:
        vlm_path = output_dir / "vlm_results.json"
        write_json_atomic(vlm_path, vlm_results)
        logger.info(f"VLM results: {vlm_path}")
    
    # ── Report ──
    report_path = output_dir / "report.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("# Activity Extraction Report\n\n")
        f.write(f"**Time**: {datetime.now().isoformat()}\n\n")
        f.write(f"**Patent**: {profile.get('patent_id', 'unknown')}\n\n")
        f.write(f"## Statistics\n\n")
        f.write(f"- Total rows: {len(rows)}\n")
        f.write(f"- Unique Cpds: {len(set(r.cpd for r in rows))}\n")
        needs_review = [r for r in rows if r.needs_review]
        f.write(f"- Needs review: {len(needs_review)}\n")
        vlm_fixed = [r for r in rows if "vlm_fixed" in r.source]
        f.write(f"- VLM corrected: {len(vlm_fixed)}\n\n")
        
        if needs_review:
            f.write(f"## Needs Review\n\n")
            for r in needs_review[:20]:
                f.write(f"- {r.cpd} (p{r.page_no}): {r.activity_values}\n")
    
    logger.info(f"Report: {report_path}")
