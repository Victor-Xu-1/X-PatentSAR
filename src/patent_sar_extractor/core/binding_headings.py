"""Heading detection and bounded active-compound focus windows."""

from __future__ import annotations

import logging
import re
from concurrent.futures import (
    ThreadPoolExecutor,
    as_completed,
)
from typing import (
    Any,
    Dict,
    List,
    Optional,
    Tuple,
)

from .binding_labels import (
    _base_cpd_num,
    _normalise_compound_label,
    _ocr_confusable_num_pattern,
)
from .binding_ocr import (
    _get_ocr_line_coords,
    fitz,
)

logger = logging.getLogger(__name__)


def _extract_heading_blocks_from_page(
    page_no: int,
    words: list,
    prefix: str,
    pattern: str,
    ocr_text: str = "",
    ocr_coords: Optional[List[Tuple[float, str]]] = None,
) -> List[Dict]:
    heading_pattern = re.compile(pattern, re.IGNORECASE)
    blocks = []
    seen = set()

    def add_block(
        cpd_label: str, y0: float, x0: float, word_index: int, line_text: str
    ) -> None:
        label_key = _normalise_compound_label(cpd_label)
        cpd_num = _base_cpd_num(label_key)
        if not label_key or cpd_num is None:
            return
        cpd_id = f"{prefix}{label_key}"
        dedup_key = (page_no, cpd_id)
        if dedup_key in seen:
            return
        seen.add(dedup_key)
        blocks.append(
            {
                "cpd": cpd_id,
                "cpd_num": cpd_num,
                "cpd_label": label_key,
                "prefix": prefix,
                "page_no": page_no,
                "y0": y0,
                "x0": x0,
                "word_index": word_index,
                "line_text": line_text[:120],
            }
        )

    if words:
        lines: Dict[int, list] = {}
        for w in words:
            y_key = round(w[1] / 5) * 5
            lines.setdefault(y_key, []).append(w)

        for y_key in sorted(lines.keys()):
            line_words = sorted(lines[y_key], key=lambda w: w[0])
            line_text = " ".join([w[4] for w in line_words])
            for m in heading_pattern.finditer(line_text):
                first_word = line_words[0]
                add_block(m.group(1), first_word[1], first_word[0], 0, line_text)
        return blocks

    if ocr_text:
        if ocr_coords:
            for y0_coord, line_text in ocr_coords:
                for m in heading_pattern.finditer(line_text):
                    add_block(m.group(1), y0_coord, 0, 0, line_text.strip())
        else:
            lines = ocr_text.replace("\n", "\n").split("\n")
            if len(lines) <= 1:
                lines = re.split(r"[。；;\n]", ocr_text)
            for line_idx, line_text in enumerate(lines):
                for m in heading_pattern.finditer(line_text):
                    # OCR cache text may not include coordinates. Keep a
                    # line-order y estimate so adjacent Chinese examples
                    # on the same page do not collapse into y=0 and force
                    # unsafe cross-page/previous-page fallbacks.
                    add_block(
                        m.group(1), float(line_idx) * 14.0, 0, 0, line_text.strip()
                    )
    return blocks


def _scan_heading_page(
    pdf_path: str,
    page_no: int,
    prefix: str,
    pattern: str,
    ocr_text: str = "",
    ocr_coords: Optional[List[Tuple[float, str]]] = None,
) -> List[Dict]:
    doc = fitz.open(pdf_path)
    try:
        page = doc[page_no - 1]
        words = page.get_text("words")
        return _extract_heading_blocks_from_page(
            page_no, words, prefix, pattern, ocr_text=ocr_text, ocr_coords=ocr_coords
        )
    finally:
        doc.close()


def _find_synthesis_blocks_cpd(
    doc, page_numbers: Optional[List[int]] = None
) -> List[Dict]:
    """查找 "Synthesis of Cpd-N" 区块。

    用于 Cpd-N 风格专利（如 WO2026067249）。
    """
    blocks = []
    synthesis_pattern = re.compile(r"Synthesis", re.IGNORECASE)
    cpd_pattern = re.compile(r"Cpd[-\s]?(\d+)", re.IGNORECASE)

    for page_no in page_numbers or list(range(1, len(doc) + 1)):
        page = doc[page_no - 1]
        words = page.get_text("words")

        for i, word in enumerate(words):
            word_text = word[4]
            if synthesis_pattern.search(word_text):
                has_of = False
                has_other_synthesis = False
                for j in range(i + 1, min(i + 3, len(words))):
                    if words[j][4].lower() == "of":
                        has_of = True
                    if synthesis_pattern.search(words[j][4]):
                        has_other_synthesis = True

                if not has_of or has_other_synthesis:
                    continue

                search_words = words[i : i + 50]
                search_text = " ".join([w[4] for w in search_words])
                cpd_match = cpd_pattern.search(search_text)
                if cpd_match:
                    cpd_num = int(cpd_match.group(1))
                    blocks.append(
                        {
                            "cpd": f"Cpd-{cpd_num}",
                            "cpd_num": cpd_num,
                            "prefix": "Cpd-",
                            "page_no": page_no,
                            "y0": word[1],
                            "word_index": i,
                        }
                    )

    blocks.sort(key=lambda x: (x["page_no"], x["y0"]))
    return blocks


def _find_heading_blocks(
    doc,
    prefix: str = "Example",
    pattern: str = r"Example\s*(\d+)",
    ocr_text_map: Optional[Dict[int, str]] = None,
    ocr_line_map: Optional[Dict[int, List[Tuple[float, str]]]] = None,
    page_numbers: Optional[List[int]] = None,
    workers: int = 1,
) -> List[Dict]:
    """查找标题式化合物区块。

    用于 Example N / Intermediate N / Compound N 风格专利。
    支持多编号合并如 "Intermediates 3 and 4"。

    Args:
        doc: fitz.Document
        prefix: 前缀名 (如 "Example", "实施例")
        pattern: 正则模式
        ocr_text_map: {page_idx: full_text} from OCR, used as fallback for scanned PDFs
    """
    blocks = []
    pages_to_scan = page_numbers or list(range(1, len(doc) + 1))
    workers = max(1, int(workers or 1))

    if workers <= 1 or len(pages_to_scan) <= 1:
        for page_no in pages_to_scan:
            page = doc[page_no - 1]
            page_idx = page_no - 1
            words = page.get_text("words")
            text = (ocr_text_map or {}).get(page_idx, "")
            coords = (ocr_line_map or {}).get(page_idx)
            if not words and not text and coords is None:
                coords = _get_ocr_line_coords(page)
            blocks.extend(
                _extract_heading_blocks_from_page(
                    page_no,
                    words,
                    prefix,
                    pattern,
                    ocr_text=text,
                    ocr_coords=coords,
                )
            )
    else:
        pdf_path = getattr(doc, "name", "")
        if not pdf_path:
            for page_no in pages_to_scan:
                page = doc[page_no - 1]
                page_idx = page_no - 1
                blocks.extend(
                    _extract_heading_blocks_from_page(
                        page_no,
                        page.get_text("words"),
                        prefix,
                        pattern,
                        ocr_text=(ocr_text_map or {}).get(page_idx, ""),
                        ocr_coords=(ocr_line_map or {}).get(page_idx),
                    )
                )
        else:
            max_workers = min(workers, len(pages_to_scan))
            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                future_map = {
                    pool.submit(
                        _scan_heading_page,
                        pdf_path,
                        page_no,
                        prefix,
                        pattern,
                        (ocr_text_map or {}).get(page_no - 1, ""),
                        (ocr_line_map or {}).get(page_no - 1),
                    ): page_no
                    for page_no in pages_to_scan
                }
                for future in as_completed(future_map):
                    try:
                        blocks.extend(future.result())
                    except Exception as exc:
                        logger.debug(
                            "Heading scan failed on page %s: %s",
                            future_map[future],
                            exc,
                        )
    blocks.sort(key=lambda x: (x["page_no"], x["y0"]))
    return blocks


def _find_missing_blocks_via_ocr_text(
    doc,
    blocks: List[Dict],
    pages_text: Dict[int, str],
    prefix: str,
    pattern: str,
) -> List[Dict]:
    """OCR 文本回退补漏：fitz 文本层找不到的编号，通过 OCR 全文搜索补回。

    适用于嵌入在流程图图片中的文字（如 "Example7", "Intermediate 14"）。
    通过上下文锚点（段落号 [00191]、INT-xx 缩写等）在 fitz 层中定位 y0。
    """
    heading_pattern = re.compile(pattern, re.IGNORECASE)

    # 收集已找到的编号
    found_nums = set()
    for b in blocks:
        if b["prefix"] == prefix:
            found_nums.add(b["cpd_num"])

    # 在 OCR 全文中搜索
    ocr_nums = set()
    ocr_locations: List[Tuple[int, int, str]] = []
    for page_idx, text in pages_text.items():
        page_idx = int(page_idx)
        for m in heading_pattern.finditer(text):
            cpd_num = int(m.group(1))
            ocr_nums.add(cpd_num)
            start = max(0, m.start() - 200)
            end = min(len(text), m.end() + 200)
            ctx = text[start:end]
            ocr_locations.append((page_idx, cpd_num, ctx))

    missing_nums = ocr_nums - found_nums
    if not missing_nums:
        return []

    logger.info(
        f"🔍 OCR回退: {prefix}在fitz层缺{len(missing_nums)}个 → {sorted(missing_nums)}"
    )

    new_blocks = []
    for page_idx, cpd_num, ctx in ocr_locations:
        if cpd_num not in missing_nums:
            continue

        page_no = page_idx + 1  # 转为 1-indexed
        y0_estimated = None
        x0_estimated = 72.0  # 默认左边距

        # 策略1: 上下文锚点映射
        anchor_patterns = [
            (r"\[(\d{5,6})\]", "paragraph"),
            (r"INT[-\s]?(\d+)", "int_abbrev"),
        ]

        page = doc[page_idx]
        words = page.get_text("words")

        for anchor_pat, anchor_type in anchor_patterns:
            anchor_matches = list(re.finditer(anchor_pat, ctx, re.IGNORECASE))
            if not anchor_matches:
                continue
            for am in anchor_matches:
                anchor_text = am.group(0)
                for w in words:
                    if w[4].strip() == anchor_text.strip():
                        y0_estimated = w[1]
                        logger.info(
                            f"   {prefix}{cpd_num} p{page_no}: "
                            f"锚点'{anchor_text}' → y0={y0_estimated:.0f}"
                        )
                        break
                if y0_estimated is not None:
                    break
            if y0_estimated is not None:
                break

        # 策略2: 同页已有 block 做插值
        if y0_estimated is None:
            same_page_blocks = [b for b in blocks if b["page_no"] == page_no]
            if same_page_blocks:
                avg_y0 = sum(b["y0"] for b in same_page_blocks) / len(same_page_blocks)
                y0_estimated = avg_y0
                logger.info(
                    f"   {prefix}{cpd_num} p{page_no}: 无锚点，用插值y0={y0_estimated:.0f}"
                )
            else:
                y0_estimated = 400.0
                logger.info(
                    f"   {prefix}{cpd_num} p{page_no}: 无锚点无参考，用默认y0=400"
                )

        new_blocks.append(
            {
                "cpd": f"{prefix}{cpd_num}",
                "cpd_num": cpd_num,
                "prefix": prefix,
                "page_no": page_no,
                "y0": y0_estimated,
                "x0": x0_estimated,
                "word_index": -1,  # 标记为 OCR 回退
                "line_text": f"[OCR回退] {ctx[:100]}",
                "source": "ocr_fallback",
            }
        )

    return new_blocks


def _find_blocks_auto(
    doc,
    pages_text: Dict[int, str],
    ocr_line_map: Optional[Dict[int, List[Tuple[float, str]]]] = None,
    page_numbers: Optional[List[int]] = None,
    workers: int = 1,
) -> Tuple[List[Dict], str]:
    """自动检测化合物编号格式并查找区块。

    Returns:
        (blocks, detected_style) — 区块列表和检测到的风格
    """
    all_text = "\n".join(pages_text.values())

    cpd_count = len(set(re.findall(r"Cpd[-\s]?(\d+)", all_text, re.IGNORECASE)))
    example_count = len(set(re.findall(r"Example\s*(\d+)", all_text, re.IGNORECASE)))
    intermediate_count = len(
        set(re.findall(r"Intermediate\s+(\d+)", all_text, re.IGNORECASE))
    )
    int_count = len(set(re.findall(r"INT[-\s]?(\d+)", all_text, re.IGNORECASE)))
    compound_count = len(set(re.findall(r"Compound\s*(\d+)", all_text, re.IGNORECASE)))
    # Chinese patterns
    shili_count = len(set(re.findall(r"实施例\s*(\d+)", all_text)))
    compound_cn_count = len(set(re.findall(r"化合物\s*(\d+)", all_text)))

    logger.info(
        f"📊 编号模式检测: Cpd={cpd_count}, Example={example_count}, "
        f"Intermediate={intermediate_count}, INT={int_count}, Compound={compound_count}, "
        f"实施例={shili_count}, 化合物={compound_cn_count}"
    )

    all_blocks: List[Dict] = []
    detected_style = "unknown"

    # Helper: filter out X-N pattern compounds (Compound 1-1, 化合物2-2, etc.)
    # These are synthesis intermediates, not final products.
    _X_N_RE = re.compile(r"[-]\d+$")

    def _filter_xn(blocks: List[Dict], label: str = "") -> List[Dict]:
        filtered = [b for b in blocks if not _X_N_RE.search(b.get("cpd", ""))]
        if len(filtered) < len(blocks):
            skipped = [b["cpd"] for b in blocks if b not in filtered]
            logger.info(
                f"  ⚠️  过滤 {len(blocks) - len(filtered)} 个中间体 ({label}): {', '.join(skipped)}"
            )
        return filtered

    # Priority: Chinese 实施例/化合物 first, then Cpd, then Compound/Example.
    # A few biology "Example N" assay sections must not override hundreds of
    # synthesis "Compound N" final-product labels.
    if shili_count >= 2:
        logger.info(
            f"🧪 检测到 实施例 N 格式 ({shili_count}个)，使用 heading 模式 (中文)"
        )
        ex_blocks = _find_heading_blocks(
            doc,
            prefix="实施例",
            pattern=r"实施例\s*(\d+)",
            ocr_text_map=pages_text,
            ocr_line_map=ocr_line_map,
            page_numbers=page_numbers,
            workers=workers,
        )
        all_blocks.extend(ex_blocks)
        detected_style = "heading"
    elif compound_cn_count >= 2:
        logger.info(
            f"🧪 检测到 化合物 N 格式 ({compound_cn_count}个)，使用 heading 模式 (中文)"
        )
        cp_blocks = _find_heading_blocks(
            doc,
            prefix="化合物",
            pattern=r"化合物\s*(\d+)",
            ocr_text_map=pages_text,
            ocr_line_map=ocr_line_map,
            page_numbers=page_numbers,
            workers=workers,
        )
        all_blocks.extend(cp_blocks)
        detected_style = "heading_compound_cn"
    elif cpd_count >= 5:
        logger.info(f"🧪 检测到 Cpd-N 格式 ({cpd_count}个)，使用 synthesis_of 模式")
        all_blocks = _find_synthesis_blocks_cpd(doc, page_numbers=page_numbers)
        detected_style = "synthesis_of"
    elif compound_count >= 5:
        logger.info(
            f"🧪 检测到 Compound N 格式 ({compound_count}个)，使用 heading 模式"
        )
        cp_blocks = _find_heading_blocks(
            doc,
            prefix="Compound",
            pattern=r"Compound\s*(\d+)",
            ocr_text_map=pages_text,
            ocr_line_map=ocr_line_map,
            page_numbers=page_numbers,
            workers=workers,
        )
        all_blocks.extend(cp_blocks)
        detected_style = "heading_compound"
    elif example_count >= 2:
        logger.info(f"🧪 检测到 Example N 格式 ({example_count}个)，使用 heading 模式")
        ex_blocks = _find_heading_blocks(
            doc,
            prefix="Example",
            pattern=r"Example\s*(\d+[A-Z]?)",
            ocr_text_map=pages_text,
            ocr_line_map=ocr_line_map,
            page_numbers=page_numbers,
            workers=workers,
        )
        all_blocks.extend(ex_blocks)
        detected_style = "heading"

        if intermediate_count >= 2:
            logger.info(
                f"🧪 同时检测到 Intermediate N ({intermediate_count}个)，合并提取"
            )
            int_blocks = _find_heading_blocks(
                doc,
                prefix="Intermediate",
                pattern=r"Intermediate\s+(\d+[A-Z]?)",
                ocr_text_map=pages_text,
                ocr_line_map=ocr_line_map,
                page_numbers=page_numbers,
                workers=workers,
            )
            all_blocks.extend(int_blocks)
            detected_style = "heading_mixed"
    elif intermediate_count >= 2:
        logger.info(f"🧪 仅检测到 Intermediate N ({intermediate_count}个)")
        int_blocks = _find_heading_blocks(
            doc,
            prefix="Intermediate",
            pattern=r"Intermediate\s+(\d+[A-Z]?)",
            ocr_text_map=pages_text,
            ocr_line_map=ocr_line_map,
            page_numbers=page_numbers,
            workers=workers,
        )
        all_blocks.extend(int_blocks)
        detected_style = "heading_intermediate"
    else:
        logger.warning("⚠️ 未检测到任何已知化合物编号模式")

    all_blocks.sort(key=lambda x: (x["page_no"], x["y0"]))
    logger.info(f"📋 最终找到 {len(all_blocks)} 个化合物区块")
    return all_blocks, detected_style


def _build_active_focus_windows(
    all_blocks: List[Dict], active_cpds: List[str]
) -> Dict[int, List[Tuple[float, float]]]:
    active_bases = {_base_cpd_num(cpd) for cpd in active_cpds}
    active_bases.discard(None)
    if not active_bases:
        return {}

    by_page: Dict[int, List[Dict]] = {}
    for block in all_blocks:
        by_page.setdefault(int(block.get("page_no") or 0), []).append(block)

    windows: Dict[int, List[Tuple[float, float]]] = {}
    for page_no, page_blocks in by_page.items():
        page_blocks = sorted(page_blocks, key=lambda b: float(b.get("y0") or 0))
        page_windows: List[Tuple[float, float]] = []
        for idx, block in enumerate(page_blocks):
            cpd_num = int(block.get("cpd_num") or 0)
            if cpd_num not in active_bases:
                continue
            start = max(0.0, float(block.get("y0") or 0) - 40.0)
            next_y = (
                float(page_blocks[idx + 1].get("y0") or 0)
                if idx + 1 < len(page_blocks)
                else start + 320.0
            )
            end = max(start + 120.0, next_y + 60.0)
            page_windows.append((start, end))
        if page_windows:
            windows[page_no] = page_windows
    return windows


def _insert_missing_active_heading_blocks(
    all_blocks: List[Dict],
    active_cpds: List[str],
    pages_text: Optional[Dict[int, str]] = None,
) -> List[Dict]:
    """Add conservative synthetic heading blocks for active examples missed by OCR.

    Some scanned Chinese examples have titles like "实施例 25" degraded enough
    that the title scanner skips them, while neighboring examples are detected
    normally. For active-led runs, insert only missing active numbers that sit
    between detected examples, using the previous block's page as a safe anchor.
    """
    active_bases = sorted(
        {_base_cpd_num(cpd) for cpd in active_cpds if _base_cpd_num(cpd)}
    )
    if not active_bases or len(all_blocks) < 2:
        return all_blocks

    by_num = {int(b.get("cpd_num") or 0): b for b in all_blocks if b.get("cpd_num")}
    additions: List[Dict] = []
    existing_additions: set[int] = set()
    for num in active_bases:
        if num in by_num or num in existing_additions:
            continue
        similar_re = re.compile(
            rf"(?:Examples?|Compounds?)\s*{num}(?![\dA-Za-z-])"
            rf"[^\n]{{0,120}}(?:prepared|following|similar procedure)",
            re.IGNORECASE,
        )
        matched: Optional[Tuple[int, int, str]] = None
        for page_idx, text in sorted((pages_text or {}).items()):
            for line_no, line in enumerate(str(text or "").splitlines()):
                if similar_re.search(line):
                    matched = (int(page_idx), line_no, line.strip())
                    break
            if matched:
                break
        if not matched:
            continue
        matched_page_idx, matched_line_no, matched_line = matched
        additions.append(
            {
                "cpd": f"Example{num}",
                "cpd_num": num,
                "prefix": "Example",
                "page_no": matched_page_idx + 1,
                "y0": float(matched_line_no) * 14.0,
                "x0": 0,
                "word_index": 0,
                "line_text": f"synthetic active similar-procedure heading: {matched_line[:80]}",
                "synthetic": True,
            }
        )
        existing_additions.add(num)

    for num in active_bases:
        if num in by_num or num in existing_additions:
            continue
        prev_nums = [n for n in by_num if n < num]
        next_nums = [n for n in by_num if n > num]
        if not prev_nums or not next_nums:
            continue
        prev_num = max(prev_nums)
        next_num = min(next_nums)
        if num - prev_num > 2 or next_num - num > 2:
            continue
        prev_block = by_num[prev_num]
        next_block = by_num[next_num]
        prev_page = int(prev_block.get("page_no") or 0)
        next_page = int(next_block.get("page_no") or 0)
        if prev_page <= 0 or next_page <= 0 or next_page - prev_page > 3:
            continue
        additions.append(
            {
                "cpd": f"实施例{num}",
                "cpd_num": num,
                "prefix": "实施例",
                "page_no": prev_page,
                "y0": float(prev_block.get("y0") or 0) + 1.0,
                "x0": 0,
                "word_index": 0,
                "line_text": f"synthetic active heading between 实施例{prev_num} and 实施例{next_num}",
                "synthetic": True,
            }
        )
        existing_additions.add(num)

    existing_additions = {int(b["cpd_num"]) for b in additions}
    for num in active_bases:
        if num in by_num or num in existing_additions:
            continue
        pair_patterns = []
        if num > 1:
            pair_patterns.append((num - 1, num))
        pair_patterns.append((num, num + 1))
        for left, right in pair_patterns:
            pair_re = rf"{left}\s*[,，、.]\s*{right}"
            title_re = re.compile(
                rf"(?:实施例|SCHED|SCHEDULE)?[^\n]{{0,80}}{pair_re}"
                rf"[^\n]{{0,80}}化.?[合台]物[^\n]{{0,80}}{pair_re}"
                rf"[^\n]{{0,80}}[合台]成",
                re.IGNORECASE,
            )
            matched_page: Optional[int] = None
            for page_idx, text in sorted((pages_text or {}).items()):
                if title_re.search(str(text or "")):
                    matched_page = int(page_idx) + 1
                    break
            if matched_page is None:
                continue
            additions.append(
                {
                    "cpd": f"实施例{num}",
                    "cpd_num": num,
                    "prefix": "实施例",
                    "page_no": matched_page,
                    "y0": 0.0,
                    "x0": 0,
                    "word_index": 0,
                    "line_text": f"synthetic active paired heading {left},{right}",
                    "synthetic": True,
                }
            )
            existing_additions.add(num)
            break

    existing_additions = {int(b["cpd_num"]) for b in additions}
    for num in active_bases:
        if num in by_num or num in existing_additions:
            continue
        similar_re = re.compile(
            rf"(?:Examples?|Compounds?)\s*{num}(?![\dA-Za-z-])"
            rf"[^\n]{{0,120}}(?:prepared|following|similar procedure)",
            re.IGNORECASE,
        )
        matched: Optional[Tuple[int, int, str]] = None
        for page_idx, text in sorted((pages_text or {}).items()):
            for line_no, line in enumerate(str(text or "").splitlines()):
                if similar_re.search(line):
                    matched = (int(page_idx), line_no, line.strip())
                    break
            if matched:
                break
        if not matched:
            continue
        matched_page_idx, matched_line_no, matched_line = matched
        additions.append(
            {
                "cpd": f"Example{num}",
                "cpd_num": num,
                "prefix": "Example",
                "page_no": matched_page_idx + 1,
                "y0": float(matched_line_no) * 14.0,
                "x0": 0,
                "word_index": 0,
                "line_text": f"synthetic active similar-procedure heading: {matched_line[:80]}",
                "synthetic": True,
            }
        )
        existing_additions.add(num)

    existing_additions = {int(b["cpd_num"]) for b in additions}
    for num in active_bases:
        if num in by_num or num in existing_additions or "5" not in str(num):
            continue
        fuzzy = _ocr_confusable_num_pattern(num)
        title_re = re.compile(
            rf"(?:实施例|化合物)[^\n]{{0,12}}{fuzzy}(?![\dA-Za-z-])"
            rf"|(?:得到|制备得到|分离制备得到)[^\n]{{0,50}}化.?[合台]物[^\n]{{0,8}}{fuzzy}(?![\dA-Za-z-])",
            re.IGNORECASE,
        )
        matches: List[Tuple[int, int, int, str]] = []
        for page_idx, text in sorted((pages_text or {}).items()):
            for line_no, line in enumerate(str(text or "").splitlines()):
                if not title_re.search(line):
                    continue
                has_product_context = bool(
                    re.search(r"(?:得到|制备得到|分离制备得到|化.?[合台]物)", line)
                )
                has_heading_context = bool(re.search(r"实施例", line))
                score = 0 if has_product_context and not has_heading_context else 1
                matches.append((score, int(page_idx), line_no, line.strip()))
        if not matches:
            continue
        _score, matched_page_idx, matched_line_no, matched_line = min(
            matches, key=lambda item: (item[0], item[1], item[2])
        )
        additions.append(
            {
                "cpd": f"实施例{num}",
                "cpd_num": num,
                "prefix": "实施例",
                "page_no": matched_page_idx + 1,
                "y0": float(matched_line_no) * 14.0,
                "x0": 0,
                "word_index": 0,
                "line_text": f"synthetic active OCR-confusable heading: {matched_line[:80]}",
                "synthetic": True,
            }
        )
        existing_additions.add(num)

    if additions:
        all_blocks = [*all_blocks, *additions]
        all_blocks.sort(key=lambda x: (x["page_no"], x["y0"], x["cpd_num"]))
        logger.info(
            "   活性编号补漏: 新增 %d 个合成标题块 %s",
            len(additions),
            [b["cpd"] for b in additions],
        )
    return all_blocks


def _filter_items_by_focus_windows(
    items: List[Dict], windows: Optional[List[Tuple[float, float]]], margin: float = 0.0
) -> List[Dict]:
    if not windows:
        return items
    filtered = []
    for item in items:
        y = float(item.get("y", item.get("y0", 0)) or 0)
        y1 = float(item.get("y1", y) or y)
        for start, end in windows:
            if y1 >= start - margin and y <= end + margin:
                filtered.append(item)
                break
    return filtered


def find_binding_blocks(
    doc: Any,
    pages_text: dict[int, str],
    cached_line_map: dict[int, list[tuple[float, str]]],
    page_indices: list[int],
    bind_workers: int,
) -> tuple[list[dict[str, Any]], str]:
    logger.info("🔍 自动检测化合物编号格式...")
    all_blocks, detected_style = _find_blocks_auto(
        doc,
        pages_text,
        ocr_line_map=cached_line_map,
        page_numbers=[i + 1 for i in page_indices],
        workers=bind_workers,
    )
    logger.info(f"   检测风格: {detected_style}")
    logger.info(f"   找到 {len(all_blocks)} 个化合物区块")

    for b in all_blocks[:10]:
        logger.info(f"   → {b['cpd']} (p{b['page_no']}, y0={b['y0']:.0f})")
    if len(all_blocks) > 10:
        logger.info(f"   ... 还有 {len(all_blocks) - 10} 个")

    # ── 4. OCR 回退补漏 ────────────────────────────────────────
    if detected_style in ("heading", "heading_mixed", "heading_intermediate"):
        # 对 Example 和 Intermediate 分别做 OCR 补漏
        for prefix, pattern in [
            ("Example", r"Example\s*(\d+)"),
            ("Intermediate", r"Intermediate\s+(\d+)"),
        ]:
            prefix_blocks = [b for b in all_blocks if b.get("prefix") == prefix]
            if prefix_blocks:
                ocr_new = _find_missing_blocks_via_ocr_text(
                    doc, prefix_blocks, pages_text, prefix, pattern
                )
                if ocr_new:
                    all_blocks.extend(ocr_new)
                    all_blocks.sort(key=lambda x: (x["page_no"], x["y0"]))
                    logger.info(f"   OCR补漏: {prefix} 新增 {len(ocr_new)} 个区块")
    return all_blocks, detected_style
