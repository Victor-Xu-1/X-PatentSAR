"""Exclude explicit intermediate role labels, never guessed I-prefix namespaces."""

from .source_role_terms import intermediate_source_label


def is_intermediate(item: dict) -> bool:
    """判断一个化合物条目是否为Intermediate(中间体)。

    检查优先级：
    1. prefix 字段（标准绑定输出）
    2. cpd_id 字段 (SMILES结果)
    3. cpd 字段 (绑定结果)
    4. label 字段 (通用标签)
    """
    return any(
        intermediate_source_label(item.get(field))
        for field in ("prefix", "cpd_id", "cpd", "label")
    )


def filter_examples_only(items: list) -> list:
    """Exclude literal intermediate labels while preserving other source entries.

    Args:
        items: 化合物条目列表（bindings或SMILES结果）

    Returns:
        过滤后的列表；不猜测其他编号前缀或把记录提升为已验收化合物。

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
        print(
            f"[cpd_filter] Filtered out {removed} Intermediate(s), "
            f"kept {len(filtered)} entries (from {before} total)"
        )
    return filtered
