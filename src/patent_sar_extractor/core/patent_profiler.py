"""
Patent Profiler — 自动页面分类

扫描 PDF 每页，自动分类为 synthesis / activity / other，
检测 Cpd 前缀模式，识别表格布局类型。

页面范围通过内容探测，不依赖特定专利的固定页码。
"""

import os
import re
import logging
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from typing import Optional

try:
    import fitz  # PyMuPDF — 可选，仅直接打开PDF时需要
except ImportError:
    fitz = None

logger = logging.getLogger(__name__)

# ---- OCR fallback for scanned PDFs ----
_OCR_ENGINE = None


def _tesseract_lang() -> str:
    return os.environ.get("PATENTSAR_TESSERACT_LANG", "chi_sim+eng")

def _get_ocr_engine():
    """Lazy-init the shared OCR engine for scanned PDFs."""
    global _OCR_ENGINE
    if _OCR_ENGINE is None:
        try:
            from patent_sar_extractor.core.page_ocr_cache import get_ocr_engine
            _OCR_ENGINE = get_ocr_engine()
            if _OCR_ENGINE:
                logger.info("Shared OCR engine loaded: %s", _OCR_ENGINE[0])
            else:
                logger.warning("No shared OCR engine available")
        except Exception as exc:
            logger.warning("Shared OCR engine unavailable: %s", exc)
            _OCR_ENGINE = False
    return _OCR_ENGINE

def _ocr_page_fallback(page, dpi: int = 150) -> str:
    """OCR a fitz.Page when no text is extractable."""
    engine_info = _get_ocr_engine()
    if engine_info is None or fitz is None:
        return ""
    try:
        from patent_sar_extractor.core.page_ocr_cache import page_text
        return page_text(page, ocr_engine=engine_info, min_native_chars=1)
    except Exception as e:
        logger.warning(f"OCR failed on page: {e}")
    return ""

# ---- 关键词规则 ----
ACTIVITY_KEYWORDS = re.compile(
    r"IC50|DC50|EC50|Ki\b|Kd\b|Dmax|nM\b|µM\b|μM\b|inhibit|cell viability|"
    r"GI50|CC50|EC90|IC90|pIC50|pKi|Emax|% inhib",
    re.IGNORECASE,
)

SYNTHESIS_KEYWORDS = re.compile(
    r"Synthesis of|Step\s+\d+|Scheme\s+\d+|Intermediate|Preparation of|"
    r"General procedure|Synthetic|合成|MS\s*m/z|NMR|DMSO|ESI",
    re.IGNORECASE,
)

# Cpd密集检测正则（用于识别活性数据表页）
CPD_DENSE_RE = re.compile(r"Cpd[-\s]?\d+", re.IGNORECASE)

# Cpd 前缀检测模式（按优先级排序）
# NOTE: Chinese 实施例 / 化合物 优先级高于英文 Compound/Example — 避免
# 从多步合成路线（"第一步"等中间体页面）误检到 Compound N。
CPD_PREFIX_PATTERNS = [
    (r"实施例\s*(\d+)", "实施例"),
    (r"化合物\s*(\d+)", "化合物"),
    (r"Cpd[-\s]?(\d+)", "Cpd-"),
    (r"Example[-\s]+(\d+)", "Example "),
    (r"Compound[-\s]+(\d+)", "Compound "),
    (r"Cmpd\.?\s*(\d+)", "Cmpd "),
    (r"Int[-\s]?(\d+)", "Int-"),
]

# 每页读取的前N个字符
CHARS_PER_PAGE = 800


@dataclass
class TableSchema:
    """表格布局描述"""
    type: str = "single"  # "single" | "double" | "multi"
    split_x: Optional[float] = None
    columns: list[str] = field(default_factory=list)


@dataclass
class PatentProfile:
    """专利分析结果"""
    synthesis_pages: list[int] = field(default_factory=list)
    activity_pages: list[int] = field(default_factory=list)
    other_pages: list[int] = field(default_factory=list)
    cpd_prefix: str = "Cpd-"
    cpd_pattern: str = r"Cpd[-\s]?(\d+)"
    table_schema: TableSchema = field(default_factory=TableSchema)
    page_count: int = 0


class PatentProfiler:
    """专利PDF自动分析器 — 页面分类 + Cpd前缀检测"""

    def profile(self, doc) -> dict:
        """
        分析PDF文档，返回页面分类和元数据。

        Args:
            doc: fitz.Document 对象 或 dict[int, str] (页码→文本)

        Returns:
            dict with keys:
                synthesis_pages, activity_pages, other_pages,
                cpd_prefix, cpd_pattern, table_schema, page_count
        """
        # 兼容两种输入：fitz.Document 或 dict[int, str]
        is_dict_input = isinstance(doc, dict)
        page_count = len(doc)
        logger.info(f"Profiling patent: {page_count} pages (input={'dict' if is_dict_input else 'fitz'})")

        synthesis_pages = []
        activity_pages = []
        other_pages = []
        cpd_prefix_counts: dict[str, int] = {p[1]: 0 for p in CPD_PREFIX_PATTERNS}

        for page_idx in range(page_count):
            if is_dict_input:
                text = doc[page_idx][:CHARS_PER_PAGE]
            else:
                text = doc[page_idx].get_text("text")[:CHARS_PER_PAGE]
                # Fallback to OCR if page has no extractable text
                if not text.strip():
                    text = _ocr_page_fallback(doc[page_idx])[:CHARS_PER_PAGE]

            has_activity = bool(ACTIVITY_KEYWORDS.search(text))
            has_synthesis = bool(SYNTHESIS_KEYWORDS.search(text))

            # 辅助信号：Cpd密集+数字密集 = 活性数据表页
            # (有些OCR PDF的表头可能被OCR漏掉，但数据行有大量Cpd-XX 数字 数字模式)
            cpd_count = len(CPD_DENSE_RE.findall(text))
            number_count = len(re.findall(r'\b\d{1,5}\b', text))
            is_data_table = cpd_count >= 10 and number_count >= cpd_count * 2

            if has_activity and has_synthesis:
                activity_pages.append(page_idx)
                logger.debug(f"Page {page_idx}: activity+synthesis → activity")
            elif has_activity:
                activity_pages.append(page_idx)
                logger.debug(f"Page {page_idx}: activity (keyword)")
            elif is_data_table:
                activity_pages.append(page_idx)
                logger.debug(f"Page {page_idx}: activity (data table: {cpd_count} cpds, {number_count} nums)")
            elif has_synthesis:
                synthesis_pages.append(page_idx)
                logger.debug(f"Page {page_idx}: synthesis")
            else:
                other_pages.append(page_idx)

            # 统计 Cpd 前缀
            for pattern_str, prefix in CPD_PREFIX_PATTERNS:
                matches = re.findall(pattern_str, text, re.IGNORECASE)
                if matches:
                    cpd_prefix_counts[prefix] += len(matches)

        # 选择最高频的 Cpd 前缀
        best_prefix = max(cpd_prefix_counts, key=cpd_prefix_counts.get)
        best_count = cpd_prefix_counts[best_prefix]
        if best_count == 0:
            best_prefix = "Cpd-"
            logger.warning("No Cpd prefix detected, defaulting to 'Cpd-'")

        # 反推正则模式
        best_pattern = r"Cpd[-\s]?(\d+)"
        for pattern_str, prefix in CPD_PREFIX_PATTERNS:
            if prefix == best_prefix:
                best_pattern = pattern_str
                break

        # 检测表格布局类型（从activity页判断）
        table_schema = self._detect_table_schema(doc, activity_pages)

        profile = PatentProfile(
            synthesis_pages=synthesis_pages,
            activity_pages=activity_pages,
            other_pages=other_pages,
            cpd_prefix=best_prefix,
            cpd_pattern=best_pattern,
            table_schema=table_schema,
            page_count=page_count,
        )

        logger.info(
            f"Profile: {len(synthesis_pages)} synthesis, "
            f"{len(activity_pages)} activity, "
            f"{len(other_pages)} other pages, "
            f"cpd_prefix='{best_prefix}' ({best_count} matches), "
            f"table_type='{table_schema.type}'"
        )

        return {
            "synthesis_pages": profile.synthesis_pages,
            "activity_pages": profile.activity_pages,
            "other_pages": profile.other_pages,
            "cpd_prefix": profile.cpd_prefix,
            "cpd_pattern": profile.cpd_pattern,
            "table_schema": {
                "type": profile.table_schema.type,
                "split_x": profile.table_schema.split_x,
                "columns": profile.table_schema.columns,
            },
            "page_count": profile.page_count,
        }

    def _detect_table_schema(self, doc, activity_pages: list[int]) -> TableSchema:
        """
        从activity页初步判断表格布局类型。
        详细列检测由 table_layout_analyzer.py 负责。
        """
        if not activity_pages:
            return TableSchema(type="single")

        # dict输入无word坐标信息，返回默认schema（后续table_layout_analyzer会精确检测）
        if isinstance(doc, dict):
            return TableSchema(type="double", split_x=285)  # 默认值，待后续精确检测

        # 采样第一个activity页的word坐标
        page = doc[activity_pages[0]]
        words = page.get_text("words")  # list of (x0, y0, x1, y1, text, block_no, line_no, word_no)

        if not words:
            return TableSchema(type="single")

        # 简单判断：统计x0分布是否有明显双峰
        page_width = page.rect.width
        mid_x = page_width / 2
        left_count = sum(1 for w in words if w[0] < mid_x)
        right_count = sum(1 for w in words if w[0] >= mid_x)

        # 如果右半部分文字量超过左半部分的30%，认为是双列
        if left_count > 0 and right_count / left_count > 0.3:
            return TableSchema(type="double", split_x=mid_x)

        return TableSchema(type="single")


def main():
    """CLI: 分析指定PDF"""
    import sys
    import json

    logging.basicConfig(level=logging.INFO, format="%(name)s - %(levelname)s - %(message)s")

    if len(sys.argv) < 2:
        print("Usage: python patent_profiler.py <pdf_path>")
        sys.exit(1)

    pdf_path = sys.argv[1]
    logger.info(f"Opening: {pdf_path}")
    doc = fitz.open(pdf_path)
    profiler = PatentProfiler()
    result = profiler.profile(doc)
    doc.close()

    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
