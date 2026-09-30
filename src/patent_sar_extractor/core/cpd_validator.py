"""
Cpd Validator — 化合物序列连续性校验

检查 OCR 提取的 Cpd 编号与 known_cpds 的一致性，自动发现 OCR 丢位错误。

核心算法：
  从 missing Cpd（known中有但OCR中缺失的）出发，
  在 OCR 的所有 Cpd ID 中搜索 Levenshtein 近邻匹配。

处理的两种场景：
  A. extra_cpd: OCR 中出现但 known 中没有的（如 "Cpd-47" 实为 "Cpd-47" 不存在）
  B. 丢位误读: OCR 读成合法 Cpd-X 但实际是 Cpd-XX（如 Cpd-15 误读了 Cpd-115）

该算法替代针对单个专利、单个化合物编号的硬编码修正。
"""

import re
import logging
from collections import Counter
from typing import Optional

logger = logging.getLogger(__name__)


def _levenshtein(s1: str, s2: str) -> int:
    """纯 Python Levenshtein 距离实现"""
    if len(s1) < len(s2):
        return _levenshtein(s2, s1)
    if len(s2) == 0:
        return len(s1)

    prev_row = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = prev_row[j + 1] + 1
            deletions = curr_row[j] + 1
            substitutions = prev_row[j] + (c1 != c2)
            curr_row.append(min(insertions, deletions, substitutions))
        prev_row = curr_row

    return prev_row[-1]


# 尝试使用 C 扩展版（更快）
try:
    from Levenshtein import distance as _lev_c

    def levenshtein(s1: str, s2: str) -> int:
        return _lev_c(s1, s2)

except ImportError:
    levenshtein = _levenshtein


def _extract_number(cpd_id: str, prefix: str) -> Optional[int]:
    """从 Cpd ID 提取数字部分，如 Cpd-115 → 115"""
    m = re.match(re.escape(prefix) + r"(\d+)", cpd_id)
    return int(m.group(1)) if m else None


def validate_cpd_sequence(
    extracted_rows: list[dict],
    known_cpds: set[str],
    cpd_prefix: str = "Cpd-",
    max_edit_distance: int = 2,
) -> dict:
    """
    检查 OCR 提取的 Cpd 编号与已知 Cpd 集合的一致性。

    算法（双向匹配）：
    1. Phase A — extra→missing: 对 OCR 中不在 known 的 Cpd，找 known 中最近邻
    2. Phase B — missing→all_ocr: 对 known 中缺失的 Cpd，在 OCR 全部 Cpd 中找近邻
       （处理 Cpd-15 误读 Cpd-115 这类"合法Cpd被误读"场景）

    Args:
        extracted_rows: OCR 提取的行，每行需有 "cpd" 键（如 "Cpd-15"）
                        可选 "page" 键记录来源页
        known_cpds: 从结构绑定步骤获得的完整 Cpd 集合
        cpd_prefix: Cpd 前缀（默认 "Cpd-"）
        max_edit_distance: 最大允许编辑距离（默认 2）

    Returns:
        {
            "corrections": [{"original": str, "suggested": str, "page": int,
                             "confidence": float, "type": str}],
            "missing_cpds": [str, ...],
            "extra_cpds": [str, ...],
        }
    """
    # ---- 构建 OCR Cpd 多重集（含页码） ----
    ocr_cpd_list = []  # [(cpd_id, page), ...]  保留重复
    for row in extracted_rows:
        cpd_id = row.get("cpd", "").strip()
        if cpd_id:
            page = row.get("page")
            ocr_cpd_list.append((cpd_id, page))

    ocr_unique = set(c for c, _ in ocr_cpd_list)
    ocr_counter = Counter(c for c, _ in ocr_cpd_list)
    ocr_pages = {}  # cpd_id → [page, ...]
    for cpd_id, page in ocr_cpd_list:
        ocr_pages.setdefault(cpd_id, []).append(page)

    # ---- 分类 ----
    extra_cpds = sorted(ocr_unique - known_cpds)  # OCR有但known没有
    missing_cpds = sorted(known_cpds - ocr_unique)  # known有但OCR缺失

    corrections = []
    used_missing = set()
    used_ocr = set()  # 已被修正的 OCR Cpd（避免重复匹配）

    # ---- Phase A: extra → missing ----
    for extra in extra_cpds:
        best_match = None
        best_dist = float("inf")
        for missing in missing_cpds:
            if missing in used_missing:
                continue
            dist = levenshtein(extra, missing)
            len_diff = abs(len(extra) - len(missing))
            if dist <= max_edit_distance and len_diff <= max_edit_distance and dist < best_dist:
                best_dist = dist
                best_match = missing

        if best_match is not None:
            max_len = max(len(extra), len(best_match))
            confidence = 1.0 - (best_dist / max_len) if max_len > 0 else 0.0
            if extra.startswith(cpd_prefix) and best_match.startswith(cpd_prefix):
                confidence = min(confidence + 0.1, 1.0)

            corrections.append({
                "original": extra,
                "suggested": best_match,
                "page": ocr_pages.get(extra, [None])[0],
                "confidence": round(confidence, 2),
                "type": "extra_to_missing",
            })
            used_missing.add(best_match)
            used_ocr.add(extra)
            logger.info(f"Phase A: {extra} → {best_match} (dist={best_dist})")

    # ---- Phase B: missing → all OCR (含合法Cpd) ----
    # 关键insight: Cpd-115 缺失, Cpd-15 出现2次(1次合法+1次误读)
    # → 对每个missing，在OCR全部Cpd中找近邻，如果某个OCR Cpd出现次数>1
    #   或OCR Cpd虽在known中但可能与missing对应，建议修正其中一次出现
    for missing in missing_cpds:
        if missing in used_missing:
            continue

        # 在所有 OCR Cpd（含合法的）中按距离排序搜索
        candidates = []
        for ocr_cpd in sorted(ocr_unique):
            if ocr_cpd in used_ocr:
                continue  # 已在Phase A中用过
            if ocr_cpd == missing:
                continue  # 完全匹配不需要修正
            dist = levenshtein(ocr_cpd, missing)
            len_diff = abs(len(ocr_cpd) - len(missing))
            if dist <= max_edit_distance and len_diff <= max_edit_distance:
                candidates.append((dist, ocr_cpd))

        # 按距离排序，依次尝试
        candidates.sort(key=lambda x: x[0])

        for best_dist, best_ocr in candidates:
            # ---- 安全过滤 ----
            # 如果 OCR Cpd 在 known 中且只出现1次，它是合法条目，不应修正
            # 只在以下情况建议修正：
            #   a) OCR Cpd 出现 ≥2 次（重复=可疑，其中一次可能是误读）
            #   b) OCR Cpd 不在 known 中（已在 Phase A 处理，此处跳过）
            occurrence = ocr_counter[best_ocr]
            if best_ocr in known_cpds and occurrence <= 1:
                logger.debug(
                    f"Phase B: skip {best_ocr} → {missing} "
                    f"(legitimate singleton in known, dist={best_dist})"
                )
                continue  # 尝试下一个候选

            # 计算置信度
            max_len = max(len(best_ocr), len(missing))
            confidence = 1.0 - (best_dist / max_len) if max_len > 0 else 0.0

            # 数字部分子串包含关系加分
            # Cpd-15 vs Cpd-115: 数字 15 vs 115 → "15" ⊂ "115"
            ocr_num = _extract_number(best_ocr, cpd_prefix)
            missing_num = _extract_number(missing, cpd_prefix)
            if ocr_num is not None and missing_num is not None:
                ocr_str, missing_str = str(ocr_num), str(missing_num)
                if ocr_str in missing_str or missing_str in ocr_str:
                    confidence = min(confidence + 0.15, 1.0)

            if best_ocr.startswith(cpd_prefix) and missing.startswith(cpd_prefix):
                confidence = min(confidence + 0.1, 1.0)

            # 重复出现加分
            if occurrence > 1:
                confidence = min(confidence + 0.1, 1.0)

            # 记录页码
            pages = ocr_pages.get(best_ocr, [None])
            page = pages[0] if pages else None

            corrections.append({
                "original": best_ocr,
                "suggested": missing,
                "page": page,
                "confidence": round(confidence, 2),
                "type": "ocr_misread",
                "note": f"OCR Cpd appears {occurrence}x; one may be misread",
            })
            used_missing.add(missing)
            logger.info(
                f"Phase B: {best_ocr} → {missing} (dist={best_dist}, "
                f"occurrence={occurrence}, confidence={confidence:.2f})"
            )

    # 排序
    corrections.sort(key=lambda c: -c["confidence"])

    # 最终 missing = 原missing - 已被修正匹配的
    remaining_missing = [c for c in missing_cpds if c not in used_missing]
    # 最终 extra = 原extra - 已在Phase A修正的
    remaining_extra = [c for c in extra_cpds if c not in {corr["original"] for corr in corrections if corr["type"] == "extra_to_missing"}]

    result = {
        "corrections": corrections,
        "missing_cpds": remaining_missing,
        "extra_cpds": remaining_extra,
    }

    logger.info(
        f"Cpd validation: {len(corrections)} corrections, "
        f"{len(remaining_missing)} missing, "
        f"{len(remaining_extra)} unexplained extras"
    )

    return result


def main():
    """CLI: 校验 Cpd 序列"""
    import json
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(name)s - %(levelname)s - %(message)s")

    parser = argparse.ArgumentParser(description="Validate Cpd sequence from OCR vs known Cpd set")
    parser.add_argument("--known", required=True, help="Comma-separated known Cpd IDs")
    parser.add_argument("--ocr", required=True, help="Comma-separated OCR-extracted Cpd IDs")
    parser.add_argument("--prefix", default="Cpd-", help="Cpd prefix (default: Cpd-)")
    parser.add_argument("--json-out", help="Output JSON file path")

    args = parser.parse_args()

    known_set = set(args.known.split(","))
    ocr_ids = args.ocr.split(",")

    # 构建 extracted_rows（含重复Cpd场景）
    rows = [{"cpd": c.strip()} for c in ocr_ids if c.strip()]

    result = validate_cpd_sequence(rows, known_set, args.prefix)

    output = json.dumps(result, indent=2, ensure_ascii=False)
    print(output)

    if args.json_out:
        with open(args.json_out, "w") as f:
            f.write(output)
        print(f"\nSaved to {args.json_out}")


if __name__ == "__main__":
    main()
