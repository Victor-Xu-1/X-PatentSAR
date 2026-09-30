#!/usr/bin/env python3
"""
Cpd Filter — 自动过滤Intermediate(中间体)，只保留Example(实施例)

在pipeline各步骤中统一调用，确保只输出Example化合物。

过滤逻辑：
  - 若条目有 prefix 字段，排除 prefix == "Intermediate" 的条目
  - 若条目无 prefix 但 cpd/cpd_id 以 "Intermediate" 开头，也排除
  - 7249类专利(无Intermediate)全部保留，零影响

用法:
    from patent_sar_extractor.core.cpd_filter import filter_examples_only
    bindings = filter_examples_only(bindings)
"""

import re

# 匹配 Intermediate 前缀的模式
# 注意：cpd_id 可能是 "Intermediate1"（字母数字紧连），\b 不匹配，故不加 \b
_INTERMEDIATE_RE = re.compile(r"^Intermediate", re.IGNORECASE)


def is_intermediate(item: dict) -> bool:
    """判断一个化合物条目是否为Intermediate(中间体)。

    检查优先级：
    1. prefix 字段（标准绑定输出）
    2. cpd_id 字段 (SMILES结果)
    3. cpd 字段 (绑定结果)
    4. label 字段 (通用标签)
    """
    # 优先检查 prefix 字段
    prefix = item.get("prefix", "")
    if prefix and _INTERMEDIATE_RE.match(str(prefix)):
        return True

    # 检查 cpd_id 字段（SMILES结果中常用，如 "Intermediate1"）
    cpd_id = item.get("cpd_id", "")
    if cpd_id and _INTERMEDIATE_RE.match(str(cpd_id)):
        return True

    # 检查 cpd 字段（绑定结果中，如 "Intermediate-1"）
    cpd = item.get("cpd", "")
    if cpd and _INTERMEDIATE_RE.match(str(cpd)):
        return True

    # 检查 label 字段
    label = item.get("label", "")
    if label and _INTERMEDIATE_RE.match(str(label)):
        return True

    return False


def filter_examples_only(items: list) -> list:
    """过滤掉Intermediate(中间体)，只保留Example(实施例)化合物。

    Args:
        items: 化合物条目列表（bindings或SMILES结果）

    Returns:
        过滤后的列表（仅Example）

    Example:
        >>> bindings = load_bindings("bindings.json")
        >>> examples = filter_examples_only(bindings)
        >>> print(f"Kept {len(examples)}/{len(bindings)} examples")
    """
    if not items:
        return items

    before = len(items)
    filtered = [item for item in items if not is_intermediate(item)]
    removed = before - len(filtered)

    if removed > 0:
        print(f"[cpd_filter] Filtered out {removed} Intermediate(s), "
              f"kept {len(filtered)} Example(s) (from {before} total)")
    # 无Intermediate时不输出（避免7249类专利无意义日志）

    return filtered
