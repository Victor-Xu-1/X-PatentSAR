"""Ordered generic recovery; the existing repeated checks remain pending regression evidence."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .binding_arbitration import (
    _arbitrate_with_clean_standalone_visual_products,
    _confirm_final_bindings_with_visible_cache,
    _dedupe_final_bindings_by_structure,
    _drop_unsafe_final_fragment_bindings,
    _repair_conflicting_bindings_from_visible_cache,
    _repair_fallback_bindings_with_visual_modules,
    _replace_with_exact_visible_table_labels,
)
from .binding_candidates import (
    _active_ordered_bindings,
    _is_weak_direct_visual_binding,
    _merge_binding_candidates,
)
from .binding_completion import (
    _fill_missing_active_from_visible_cache,
    _fill_missing_from_cmpd_overview_tables,
    _fill_missing_from_route_title_rows,
    _restore_safe_missing_active_bindings,
)
from .binding_fragments import (
    _merge_split_visible_label_fragments,
    _repair_same_row_fragment_bindings_to_right_product,
    _repair_weak_bindings_with_expanded_strict_fragments,
    _replace_with_expanded_strict_crops,
)
from .binding_labels import _base_cpd_num, _binding_base_num
from .binding_layouts import _extract_visual_module_bindings
from .binding_observations import _annotate_bindings_with_visible_labels
from .binding_tables import _repair_missing_structure_table_bindings
from .binding_types import BindingSelection

logger = logging.getLogger(__name__)


def recover_generic_bindings(
    doc: Any,
    selection: BindingSelection,
    processed_structures: list[dict[str, Any]],
    pages_text: dict[int, str],
    cached_line_map: dict[int, list[tuple[float, str]]],
    active_cpds: list[str],
    out: Path,
    output_dir: str,
) -> list[dict[str, Any]]:
    final_bindings = list(selection.bindings)
    visible_label_cache = selection.visible_label_cache
    visual_grid_bindings = selection.visual_grid_bindings
    before_activity_gate = len(final_bindings)
    final_bindings = _annotate_bindings_with_visible_labels(
        final_bindings, visible_label_cache
    )
    final_bindings = _active_ordered_bindings(final_bindings, active_cpds)
    if active_cpds:
        logger.info(
            f"   🎯 活性编号主导输出: {before_activity_gate} → {len(final_bindings)}，"
            "按活性表编号顺序排序并剔除非活性绑定"
        )
    active_candidate_snapshot = list(final_bindings)

    final_bindings = _repair_missing_structure_table_bindings(
        final_bindings,
        processed_structures,
        pages_text,
        active_cpds,
        ocr_line_map=cached_line_map,
    )
    final_bindings = _active_ordered_bindings(final_bindings, active_cpds)

    fallback_rules_for_repair = {
        "product_section_context",
        "heading_range_fallback",
        "structure_table_row_order",
        "structure_table_row_order_inferred",
        "structure_table_row_order_corrected",
        "paired_route_product_row_order",
        "triplet_split_row_structure_order",
        "split_reaction_product_label",
        "ocr_numeric_structure_label",
        "ocr_bare_numeric_product_label",
    }
    current_by_base = {
        _binding_base_num(binding): binding
        for binding in final_bindings
        if _binding_base_num(binding) is not None
    }
    target_repair_bases: set[int] = set()
    for cpd in active_cpds:
        base = _base_cpd_num(cpd)
        if base is None:
            continue
        current = current_by_base.get(base)
        current_rule = str(current.get("binding_rule") or "") if current else ""
        if (
            current is None
            or current_rule in fallback_rules_for_repair
            or _is_weak_direct_visual_binding(current)
        ):
            target_repair_bases.add(base)

    visual_module_bindings = _extract_visual_module_bindings(
        doc,
        processed_structures,
        active_cpds,
        pages_text,
        visible_label_cache=visible_label_cache,
        target_bases=target_repair_bases,
        ocr_line_map=cached_line_map,
    )
    if visual_module_bindings:
        before_visual_repair = len(final_bindings)
        final_bindings = _repair_fallback_bindings_with_visual_modules(
            final_bindings,
            visual_module_bindings,
            active_cpds,
            output_dir=output_dir,
        )
        logger.info(
            f"   👁 完整结构模块视觉修复: {before_visual_repair} → {len(final_bindings)}，"
            "仅覆盖缺失或文本/位置fallback绑定"
        )

    final_bindings = _fill_missing_active_from_visible_cache(
        final_bindings,
        processed_structures,
        active_cpds,
        pages_text,
        visible_label_cache,
        cached_line_map,
    )
    final_bindings = _repair_conflicting_bindings_from_visible_cache(
        final_bindings,
        processed_structures,
        active_cpds,
        pages_text,
        visible_label_cache,
        cached_line_map,
    )
    final_bindings = _annotate_bindings_with_visible_labels(
        final_bindings, visible_label_cache
    )
    final_bindings = _replace_with_exact_visible_table_labels(
        final_bindings,
        processed_structures,
        active_cpds,
        visible_label_cache,
        cached_line_map,
    )
    final_bindings = _restore_safe_missing_active_bindings(
        final_bindings,
        active_candidate_snapshot,
        processed_structures,
        active_cpds,
        visible_label_cache,
    )
    final_bindings = _fill_missing_from_cmpd_overview_tables(
        final_bindings,
        processed_structures,
        pages_text,
        active_cpds,
        cached_line_map,
    )
    final_bindings = _fill_missing_from_route_title_rows(
        final_bindings,
        processed_structures,
        pages_text,
        active_cpds,
        visible_label_cache,
        cached_line_map,
    )
    final_bindings = _annotate_bindings_with_visible_labels(
        final_bindings, visible_label_cache
    )
    final_bindings = _confirm_final_bindings_with_visible_cache(
        final_bindings,
        processed_structures,
        pages_text,
        visible_label_cache,
        cached_line_map,
    )
    final_bindings = _fill_missing_from_cmpd_overview_tables(
        final_bindings,
        processed_structures,
        pages_text,
        active_cpds,
        cached_line_map,
    )
    final_bindings = _fill_missing_from_route_title_rows(
        final_bindings,
        processed_structures,
        pages_text,
        active_cpds,
        visible_label_cache,
        cached_line_map,
    )
    final_bindings = _annotate_bindings_with_visible_labels(
        final_bindings, visible_label_cache
    )
    final_bindings = _dedupe_final_bindings_by_structure(
        final_bindings,
        active_cpds,
        visible_label_cache,
    )
    final_bindings = _fill_missing_active_from_visible_cache(
        final_bindings,
        processed_structures,
        active_cpds,
        pages_text,
        visible_label_cache,
    )
    final_bindings = _restore_safe_missing_active_bindings(
        final_bindings,
        active_candidate_snapshot,
        processed_structures,
        active_cpds,
        visible_label_cache,
    )
    final_bindings = _fill_missing_from_cmpd_overview_tables(
        final_bindings,
        processed_structures,
        pages_text,
        active_cpds,
        cached_line_map,
    )
    final_bindings = _drop_unsafe_final_fragment_bindings(
        final_bindings,
        active_cpds,
        visible_label_cache,
        processed_structures,
    )
    final_bindings = _fill_missing_active_from_visible_cache(
        final_bindings,
        processed_structures,
        active_cpds,
        pages_text,
        visible_label_cache,
    )
    final_bindings = _restore_safe_missing_active_bindings(
        final_bindings,
        active_candidate_snapshot,
        processed_structures,
        active_cpds,
        visible_label_cache,
    )
    final_bindings = _fill_missing_from_cmpd_overview_tables(
        final_bindings,
        processed_structures,
        pages_text,
        active_cpds,
        cached_line_map,
    )
    final_bindings = _fill_missing_from_route_title_rows(
        final_bindings,
        processed_structures,
        pages_text,
        active_cpds,
        visible_label_cache,
        cached_line_map,
    )
    final_bindings = _annotate_bindings_with_visible_labels(
        final_bindings, visible_label_cache
    )
    final_bindings = _repair_same_row_fragment_bindings_to_right_product(
        final_bindings,
        processed_structures,
        active_cpds,
        visible_label_cache,
    )
    final_bindings = _drop_unsafe_final_fragment_bindings(
        final_bindings,
        active_cpds,
        visible_label_cache,
        processed_structures,
    )
    final_bindings = _fill_missing_active_from_visible_cache(
        final_bindings,
        processed_structures,
        active_cpds,
        pages_text,
        visible_label_cache,
    )
    final_bindings = _fill_missing_from_cmpd_overview_tables(
        final_bindings,
        processed_structures,
        pages_text,
        active_cpds,
        cached_line_map,
    )
    final_bindings = _fill_missing_from_route_title_rows(
        final_bindings,
        processed_structures,
        pages_text,
        active_cpds,
        visible_label_cache,
        cached_line_map,
    )
    final_bindings = _annotate_bindings_with_visible_labels(
        final_bindings, visible_label_cache
    )
    final_bindings = _repair_weak_bindings_with_expanded_strict_fragments(
        final_bindings,
        processed_structures,
        active_cpds,
        pages_text,
        visible_label_cache,
        str(out),
        cached_line_map,
    )
    final_bindings = _annotate_bindings_with_visible_labels(
        final_bindings, visible_label_cache
    )
    final_bindings = _merge_split_visible_label_fragments(
        final_bindings,
        processed_structures,
        active_cpds,
        visible_label_cache,
        str(out),
    )
    final_bindings = _replace_with_expanded_strict_crops(final_bindings, str(out))
    final_bindings = _arbitrate_with_clean_standalone_visual_products(
        final_bindings,
        processed_structures,
        active_cpds,
        pages_text,
        visible_label_cache,
        cached_line_map,
    )
    if visual_grid_bindings:
        before_visual_grid_restore = len(final_bindings)
        final_bindings = _merge_binding_candidates(
            visual_grid_bindings,
            final_bindings,
            active_cpds=active_cpds,
        )
        logger.info(
            "   👁 视觉网格图下编号最终保护合并: %d → %d",
            before_visual_grid_restore,
            len(final_bindings),
        )
    return final_bindings
