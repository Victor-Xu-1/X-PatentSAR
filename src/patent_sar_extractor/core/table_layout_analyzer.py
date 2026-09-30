"""
Table Layout Analyzer — 列坐标自动检测

从 activity 页的 word-level 坐标自动检测列分割点，
从表头行自动识别指标列名。

消除的硬编码：
  - 固定列分割坐标
  - 固定假设的 "Cpd | DC50(nM) | Dmax%" 列结构

算法核心：
  利用化合物前缀词（如 Cpd-XX）的 x 坐标双峰聚类来检测列分割点，
  而非依赖 word 密度直方图的低谷（OCR PDF 的 word 分布太平坦无法用低谷检测）。
"""

import re
import logging
from typing import Optional

import fitz  # PyMuPDF
import numpy as np

logger = logging.getLogger(__name__)

# 已知活性指标列头（正则）
KNOWN_ACTIVITY_HEADERS = [
    r"DC50", r"IC50", r"EC50", r"Ki\b", r"Kd\b",
    r"Dmax", r"Emax", r"%\s*inhib", r"GI50", r"CC50",
]

ACTIVITY_HEADER_RE = re.compile("|".join(KNOWN_ACTIVITY_HEADERS), re.IGNORECASE)

# 化合物前缀检测模式（与页面分类规则共享）
CPD_PREFIX_DETECT = re.compile(
    r"Cpd[-\s]?\d+|Compound\s+\d+|Cmpd\.?\s*\d+|Example\s+\d+|Int[-\s]?\d+",
    re.IGNORECASE,
)

# ── Generic column-header classification patterns ──────────────────────
HEADER_PATTERNS: dict[str, list[str]] = {
    "cpd_id": [r"(?i)(cpd|compound|example|cmpd)[-\s]?\d*"],
    "activity_value": [r"(?i)(ic50|ec50|dc50|ki|kd|potency|mic|mic50)"],
    "activity_percent": [r"(?i)(dmax|%\s*inhib|efficacy|emax|%\s*kill|viability)"],
    "cell_line": [r"(?i)(mcf-7|hek293|hela|mda-mb|a549|sk-br|bt-474|t47d)"],
}

# Compile once at module load
_COMPILED_HEADER_PATTERNS: dict[str, list[re.Pattern]] = {
    cat: [re.compile(p) for p in pats]
    for cat, pats in HEADER_PATTERNS.items()
}

# Unit extraction: "DC50(nM)" → "nM",  "Dmax(%)" → "%"
_UNIT_RE = re.compile(r"\(([^)]+)\)\s*$")


def detect_column_layout(
    doc: fitz.Document,
    activity_pages: list[int],
    cpd_pattern: str = r"Cpd[-\s]?\d+",
) -> dict:
    """
    从 activity 页的 word-level 坐标自动检测列分割点。

    算法（Cpd聚类法）：
    1. 在所有活性页中找到匹配 cpd_pattern 的word
    2. 对这些word的x0坐标做直方图，找双峰
    3. 双峰中间的低谷即为列分割点
    4. 如果只有单峰，判定为单列布局

    Args:
        doc: fitz.Document 对象
        activity_pages: 活性页页码列表（0-indexed）
        cpd_pattern: 化合物前缀正则（默认 Cpd-\\d+）

    Returns:
        {
            "type": "single" | "double" | "multi",
            "split_xs": [float, ...],
            "column_ranges": [(x_min, x_max), ...],
        }
    """
    cpd_re = re.compile(cpd_pattern, re.IGNORECASE)

    # 收集所有Cpd前缀词的 x0, x1 坐标
    cpd_positions = []  # (x0, x1, page_idx)
    for page_idx in activity_pages:
        if page_idx >= len(doc):
            continue
        page = doc[page_idx]
        words = page.get_text("words")
        for w in words:
            # w = (x0, y0, x1, y1, text, block_no, line_no, word_no)
            if cpd_re.search(w[4]):
                cpd_positions.append((w[0], w[2], page_idx))

    if len(cpd_positions) < 4:
        logger.info(
            f"Too few Cpd words ({len(cpd_positions)}) for column detection → single column"
        )
        fallback_width = doc[0].rect.width if len(doc) > 0 else 595.0
        return {"type": "single", "split_xs": [], "column_ranges": [(0, fallback_width)]}

    page_width = doc[activity_pages[0]].rect.width if activity_pages else (doc[0].rect.width if len(doc) > 0 else 595.0)
    x0_arr = np.array([p[0] for p in cpd_positions])
    x1_arr = np.array([p[1] for p in cpd_positions])

    # 用直方图双峰检测
    try:
        from scipy.signal import find_peaks
        from scipy.ndimage import gaussian_filter1d

        hist, edges = np.histogram(x0_arr, bins=50, range=(0, page_width))
        centers = (edges[:-1] + edges[1:]) / 2

        # 高斯平滑
        smoothed = gaussian_filter1d(hist.astype(float), sigma=3)

        # 找峰，prominence=至少5%的Cpd词数
        min_prominence = max(len(cpd_positions) * 0.03, 3)
        peaks, props = find_peaks(
            smoothed, prominence=min_prominence, distance=5
        )

        if len(peaks) >= 2:
            # 取最高的2个峰
            top2_idx = np.argsort(smoothed[peaks])[-2:]
            top2 = peaks[top2_idx]
            top2.sort()

            x_left_peak = centers[top2[0]]
            x_right_peak = centers[top2[1]]

            # 初始分割：两峰的中点
            initial_split = (x_left_peak + x_right_peak) / 2

            # 精细分割：用所有word（不仅仅是Cpd词）计算精确边界
            # 收集所有word坐标
            all_words_x0 = []
            all_words_x1 = []
            for page_idx in activity_pages:
                if page_idx >= len(doc):
                    continue
                page = doc[page_idx]
                for w in page.get_text("words"):
                    if len(w[4]) >= 2:
                        all_words_x0.append(w[0])
                        all_words_x1.append(w[2])

            if all_words_x0:
                wx0 = np.array(all_words_x0)
                wx1 = np.array(all_words_x1)
                # 左列word: x0 < initial_split
                # 右列Cpd word: x0 >= initial_split 且匹配cpd_pattern
                left_mask = wx0 < initial_split
                right_cpd_mask = (wx0 >= initial_split)
                # 进一步过滤：右列Cpd词的x0
                cpd_right_x0 = x0_arr[x0_arr >= initial_split]
                if left_mask.any() and len(cpd_right_x0) > 0:
                    # 使用右列Cpd x0的第10百分位数（稳健估计，避免异常页干扰）
                    right_cpd_x0_p10 = float(np.percentile(cpd_right_x0, 10))
                    # 左列word: x0 < initial_split 且 x0 > initial_split * 0.3 (排除页眉)
                    left_data_mask = (wx0 < initial_split) & (wx0 > initial_split * 0.3)
                    if left_data_mask.any():
                        # 使用左列word x1的第90百分位数（稳健估计）
                        left_x1_p90 = float(np.percentile(wx1[left_data_mask], 90))
                        # 精确split_x = 左列word右边界 与 右列Cpd左边界 的中点
                        split_x = float((left_x1_p90 + right_cpd_x0_p10) / 2)
                        logger.info(
                            f"Refined split_x: {split_x:.1f} "
                            f"(left_x1_p90={left_x1_p90:.0f}, right_cpd_x0_p10={right_cpd_x0_p10:.0f})"
                        )
                    else:
                        split_x = float(initial_split)
                else:
                    split_x = float(initial_split)
            else:
                split_x = float(initial_split)

            # 如果有3+个峰（多列），重复找第2-3个峰之间的split
            split_xs = [split_x]
            if len(peaks) >= 3:
                top3_idx = np.argsort(smoothed[peaks])[-3:]
                top3 = peaks[top3_idx]
                top3.sort()
                for i in range(1, min(len(top3), 3)):
                    if i + 1 < len(top3):
                        between2 = smoothed[top3[i]:top3[i + 1]]
                        if len(between2) > 0:
                            saddle2 = top3[i] + np.argmin(between2)
                            split_xs.append(float(centers[saddle2]))
                split_xs.sort()

            n_cols = len(split_xs) + 1
            layout_type = "double" if n_cols == 2 else "multi"

        elif len(peaks) == 1:
            # 只有一个峰，可能是单列或Cpd位置相近
            # 检查数据覆盖范围：如果Cpd x0跨度 > page_width*0.4，可能仍是双列
            x_spread = x0_arr.max() - x0_arr.min()
            if x_spread > page_width * 0.4:
                # 尝试用简单2聚类
                split_x = _simple_kmeans_split(x0_arr)
                split_xs = [split_x] if split_x else []
                layout_type = "double" if split_xs else "single"
            else:
                logger.info("Single peak in Cpd x0 distribution → single column")
                return {
                    "type": "single",
                    "split_xs": [],
                    "column_ranges": [(0, page_width)],
                }
        else:
            logger.info("No peaks found → single column")
            return {"type": "single", "split_xs": [], "column_ranges": [(0, page_width)]}

    except ImportError:
        # scipy不可用，用简单中点法
        split_x = _simple_kmeans_split(x0_arr)
        split_xs = [split_x] if split_x else []
        layout_type = "double" if split_xs else "single"

    # 计算各列x范围
    boundaries = [0.0] + split_xs + [page_width]
    column_ranges = [(boundaries[i], boundaries[i + 1]) for i in range(len(boundaries) - 1)]

    logger.info(
        f"Column layout: type={layout_type}, split_xs={[f'{x:.1f}' for x in split_xs]}, "
        f"columns={len(column_ranges)}"
    )

    return {
        "type": layout_type,
        "split_xs": split_xs,
        "column_ranges": column_ranges,
    }


def _simple_kmeans_split(x0_arr: np.ndarray) -> Optional[float]:
    """
    简单的1D二聚类（不依赖sklearn）。
    用K-means初始化+迭代找2个聚类中心，返回中间点。
    """
    if len(x0_arr) < 4:
        return None

    # 初始化：按排序后前半/后半的均值
    sorted_x = np.sort(x0_arr)
    n = len(sorted_x)
    c1 = sorted_x[: n // 2].mean()
    c2 = sorted_x[n // 2 :].mean()

    # 迭代5次
    for _ in range(5):
        # 分配
        labels = (np.abs(x0_arr - c1) < np.abs(x0_arr - c2)).astype(int)
        labels[x0_arr < (c1 + c2) / 2] = 0
        labels[x0_arr >= (c1 + c2) / 2] = 1

        # 更新中心
        g0 = x0_arr[labels == 0]
        g1 = x0_arr[labels == 1]
        if len(g0) == 0 or len(g1) == 0:
            return None
        c1, c2 = g0.mean(), g1.mean()

    # 如果两个中心太近，认为是单列
    if abs(c2 - c1) < x0_arr.max() * 0.1:
        return None

    return float((c1 + c2) / 2)


def detect_column_headers(
    doc: fitz.Document,
    activity_pages: list[int],
    profiler_result: Optional[dict] = None,
) -> dict:
    """
    从每个活性页顶部（y < 200px）找包含已知指标关键词的文本行，
    自动识别列名和Cpd列x坐标。

    Args:
        doc: fitz.Document 对象
        activity_pages: 活性页页码列表（0-indexed）
        profiler_result: 页面画像输出（可选，用于辅助判断）

    Returns:
        {
            "headers": ["Cpd", "DC50(nM)", "Dmax(%)"],  # 实际列头
            "header_y": float,  # 列头所在y坐标
            "cpd_col_x": float,  # Cpd列的x锚点
            "header_words": [...],  # 列头单词列表（含坐标）
        }
    """
    # Cpd 前缀模式（从profiler获取或默认）
    cpd_re = re.compile(r"Cpd|Compound|Cmpd|Example", re.IGNORECASE)

    best_headers = []
    best_header_y = None
    best_cpd_col_x = None
    best_header_words = []

    for page_idx in activity_pages:
        if page_idx >= len(doc):
            continue
        page = doc[page_idx]
        words = page.get_text("words")

        # 收集 y < 200px 的文本行
        header_words = [w for w in words if w[1] < 200 and len(w[4]) >= 1]

        if not header_words:
            continue

        # 按y坐标分行（容差±5px）
        lines = _group_words_by_y(header_words, tolerance=5)

        for line_words in lines:
            line_text = " ".join(w[4] for w in line_words)
            if ACTIVITY_HEADER_RE.search(line_text) or cpd_re.search(line_text):
                # 找到表头行
                best_headers = [w[4] for w in line_words]
                best_header_y = line_words[0][1]
                best_header_words = [
                    {"text": w[4], "x0": w[0], "y0": w[1], "x1": w[2]}
                    for w in line_words
                ]
                # 找Cpd列的x坐标
                for w in line_words:
                    if cpd_re.search(w[4]):
                        best_cpd_col_x = w[0]
                        break

                logger.info(
                    f"Page {page_idx}: Found column headers: {best_headers} "
                    f"at y={best_header_y:.1f}"
                )
                break  # 只取第一个表头行

        if best_headers:
            break  # 找到就停

    return {
        "headers": best_headers,
        "header_y": best_header_y,
        "cpd_col_x": best_cpd_col_x,
        "header_words": best_header_words,
    }


def _group_words_by_y(words: list, tolerance: float = 5.0) -> list[list]:
    """按y坐标将words分组为行"""
    if not words:
        return []

    sorted_words = sorted(words, key=lambda w: (w[1], w[0]))
    groups = [[sorted_words[0]]]

    for w in sorted_words[1:]:
        if abs(w[1] - groups[-1][0][1]) <= tolerance:
            groups[-1].append(w)
        else:
            groups.append([w])

    # 每组内按x排序
    for g in groups:
        g.sort(key=lambda w: w[0])

    return groups


# ── Generic column-header classification ───────────────────────────────

def classify_column_headers(headers: list[str]) -> list[dict]:
    """
    Map detected column headers to standard categories.

    Categories:
        "cpd_id"          – compound identifier (Cpd-2, Example 1, …)
        "activity_value"  – IC50, EC50, DC50, Ki, Kd, potency, MIC, …
        "activity_percent"– Dmax, % inhibition, efficacy, …
        "cell_line"       – MCF-7, HEK293, HeLa, …
        "other"           – anything that does not match

    Numeric-only headers (e.g. "18", "46") are classified positionally:
        1st numeric after a cpd_id  → activity_value
        2nd numeric after a cpd_id  → activity_percent
    This mirrors the common WO-patent table layout: Cpd | DC50 | Dmax.

    Args:
        headers: list of header strings (one per column).

    Returns:
        List of dicts, each with keys:
            header     – original header string
            category   – one of the category strings above
            confidence – 0.0–1.0 (1.0 for regex match, lower for positional)
            unit       – extracted unit string or None  (e.g. "nM", "%")
    """
    _NUMERIC_RE = re.compile(r"^\d+(\.\d+)?$")

    results: list[dict] = []
    # Track the most-recent cpd_id index so we can positionally
    # classify numeric headers that follow it.
    last_cpd_idx: int | None = None
    # Count of numeric headers seen since the last cpd_id
    numeric_since_cpd = 0

    for i, hdr in enumerate(headers):
        # ── 1. Try regex matching against known patterns ───────────
        matched_cat: str | None = None
        match_confidence: float = 0.0

        for cat, patterns in _COMPILED_HEADER_PATTERNS.items():
            for pat in patterns:
                if pat.search(hdr):
                    matched_cat = cat
                    match_confidence = 1.0
                    break
            if matched_cat:
                break

        # ── 2. Positional classification for numeric-only headers ──
        if matched_cat is None and _NUMERIC_RE.match(hdr.strip()):
            if last_cpd_idx is not None:
                numeric_since_cpd += 1
                if numeric_since_cpd == 1:
                    matched_cat = "activity_value"
                    match_confidence = 0.7
                elif numeric_since_cpd == 2:
                    matched_cat = "activity_percent"
                    match_confidence = 0.7
                else:
                    # 3rd+ numeric after cpd – ambiguous
                    matched_cat = "other"
                    match_confidence = 0.3
            else:
                # Numeric header with no preceding cpd_id
                matched_cat = "other"
                match_confidence = 0.3

        # ── 3. Update cpd tracking ─────────────────────────────────
        if matched_cat == "cpd_id":
            last_cpd_idx = i
            numeric_since_cpd = 0

        # ── 4. Fallback ────────────────────────────────────────────
        if matched_cat is None:
            matched_cat = "other"
            match_confidence = 0.3

        # ── 5. Extract unit from trailing parentheses ──────────────
        unit_match = _UNIT_RE.search(hdr)
        unit: str | None = unit_match.group(1) if unit_match else None

        results.append({
            "header": hdr,
            "category": matched_cat,
            "confidence": match_confidence,
            "unit": unit,
        })

    return results


def main():
    """CLI: 分析指定PDF的表格布局"""
    import sys
    import json

    logging.basicConfig(level=logging.INFO, format="%(name)s - %(levelname)s - %(message)s")

    if len(sys.argv) < 2:
        print("Usage: python table_layout_analyzer.py <pdf_path> [activity_pages_csv]")
        print("  activity_pages_csv: comma-separated 0-indexed page numbers")
        sys.exit(1)

    pdf_path = sys.argv[1]
    doc = fitz.open(pdf_path)

    if len(sys.argv) >= 3:
        activity_pages = [int(x) for x in sys.argv[2].split(",")]
    else:
        # 先用profiler检测activity pages
        from patent_sar_extractor.core.patent_profiler import PatentProfiler
        profiler = PatentProfiler()
        profile = profiler.profile(doc)
        activity_pages = profile["activity_pages"]
        print(f"Auto-detected activity pages: {activity_pages}")

    layout = detect_column_layout(doc, activity_pages)
    headers = detect_column_headers(doc, activity_pages)

    doc.close()

    result = {"column_layout": layout, "column_headers": headers}
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
