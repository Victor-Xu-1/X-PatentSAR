"""Generic layout selection and heading-range candidate coordination."""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from .binding_candidates import _merge_binding_candidates
from .binding_geometry import _attach_structure_geometry, _select_best_structure_v4
from .binding_headings import (
    _build_active_focus_windows,
    _insert_missing_active_heading_blocks,
)
from .binding_labels import (
    _base_cpd_num,
    _binding_base_num,
    _extract_chinese_compound_sequence,
    _filter_examples_only,
    _is_intermediate,
    _page_has_product_context,
)
from .binding_layouts import (
    _extract_labeled_product_bindings,
    _extract_visual_grid_label_bindings,
)
from .binding_observations import (
    _annotate_bindings_with_visible_labels,
    _load_visible_label_cache,
    _precompute_visible_label_cache,
    _refine_visible_label_cache_with_page_ocr,
)
from .binding_products import (
    _product_structures_from_triplets,
    _seed_singleton_active_compound_binding,
)
from .binding_types import BinderConfig, BindingSelection

logger = logging.getLogger(__name__)


def select_generic_bindings(
    doc: Any,
    processed_structures: list[dict[str, Any]],
    pages_text: dict[int, str],
    cached_line_map: dict[int, list[tuple[float, str]]],
    active_cpds: list[str],
    all_blocks: list[dict[str, Any]],
    detected_style: str,
    output_dir: str,
    profile: dict[str, Any],
    bind_workers: int,
    include_intermediates: bool,
    config: BinderConfig,
) -> BindingSelection:
    all_blocks = _insert_missing_active_heading_blocks(
        all_blocks, active_cpds, pages_text=pages_text
    )

    active_focus_windows = _build_active_focus_windows(all_blocks, active_cpds)

    compound_sequence = _extract_chinese_compound_sequence(pages_text)

    product_structures = _product_structures_from_triplets(processed_structures)

    if not processed_structures:
        visible_label_cache: Dict[str, Dict] = {}
        labeled_bindings: List[Dict] = []
        visual_grid_bindings: List[Dict] = []
        seeded_bindings: List[Dict] = []
    else:
        visible_label_cache = _load_visible_label_cache(output_dir, profile)
        visible_label_cache = _precompute_visible_label_cache(
            processed_structures,
            output_dir,
            profile,
            visible_label_cache,
            workers=bind_workers,
        )
        visible_label_cache = _refine_visible_label_cache_with_page_ocr(
            processed_structures,
            visible_label_cache,
            cached_line_map,
            output_dir,
            profile,
        )
        labeled_bindings = _extract_labeled_product_bindings(
            doc,
            processed_structures,
            pages_text,
            active_cpds=active_cpds,
            focus_windows=active_focus_windows,
            ocr_line_map=cached_line_map,
            visible_label_cache=visible_label_cache,
        )
        visual_grid_bindings = _extract_visual_grid_label_bindings(
            processed_structures,
            active_cpds,
            visible_label_cache,
        )
        seeded_bindings = _seed_singleton_active_compound_binding(
            [],
            processed_structures,
            active_cpds,
            pages_text,
        )

    if visual_grid_bindings:
        seeded_bindings = _merge_binding_candidates(
            visual_grid_bindings, seeded_bindings, active_cpds=active_cpds
        )

    if labeled_bindings:
        # Numbered cells may cover only part of the activity set. Proven
        # labels from non-table pages still need to reach the same output.
        seeded_bindings = _merge_binding_candidates(
            seeded_bindings, labeled_bindings, active_cpds=active_cpds
        )

    if labeled_bindings:
        logger.info(
            f"   ✅ OCR结构标签绑定完成: {len(seeded_bindings)} 个产物，继续用标题区间补漏"
        )
        goto_save = False
    elif seeded_bindings:
        logger.info(
            f"   ✅ 单一主化合物结构绑定完成: {len(seeded_bindings)} 个产物，继续用标题区间补漏"
        )
        goto_save = False
    elif compound_sequence and len(compound_sequence) == len(product_structures):
        logger.info(
            f"   检测到中文实施例/化合物序列，按三结构反应行的右侧产物自动绑定: {len(product_structures)} products"
        )
        final_bindings = []
        for idx, (compound_num, best_p) in enumerate(
            zip(compound_sequence, product_structures), start=1
        ):
            cpd = f"实施例{idx}"
            final_bindings.append(
                _attach_structure_geometry(
                    {
                        "cpd": cpd,
                        "example_id": cpd,
                        "example_num": idx,
                        "compound_id": f"化合物{compound_num}",
                        "compound_num": compound_num,
                        "cpd_num": idx,
                        "prefix": "实施例",
                        "structure_id": best_p["id"],
                        "page_no": best_p["page_no"],
                        "structure_index": best_p["idx"],
                        "struct_x0": best_p["x0"],
                        "struct_y0": best_p["y0"],
                        "image_path": best_p["image_path"],
                        "candidates": 3,
                        "binding_rule": "chinese_reaction_triplet_product",
                    },
                    best_p,
                )
            )
        no_binding = []
        unbound_pages = []
        all_blocks = [
            {"cpd": b["cpd"], "cpd_num": b["cpd_num"], "prefix": b["prefix"]}
            for b in final_bindings
        ]
        detected_style = "heading_cn_reaction_triplet"
        logger.info(f"   ✅ 中文序列绑定完成: {len(final_bindings)} 个产物")
        goto_save = True
    elif not all_blocks and processed_structures:
        logger.warning("   未识别到化合物标题；按结构图页序生成 Structure-* 兜底绑定")
        final_bindings = []
        for idx, best_p in enumerate(
            sorted(
                processed_structures, key=lambda p: (p["page_no"], p["y0"], p["x0"])
            ),
            start=1,
        ):
            cpd = f"Structure-{idx:04d}"
            final_bindings.append(
                _attach_structure_geometry(
                    {
                        "cpd": cpd,
                        "example_id": cpd,
                        "example_num": idx,
                        "cpd_num": idx,
                        "prefix": "Structure",
                        "structure_id": best_p["id"],
                        "page_no": best_p["page_no"],
                        "structure_index": best_p["idx"],
                        "struct_x0": best_p["x0"],
                        "struct_y0": best_p["y0"],
                        "image_path": best_p["image_path"],
                        "candidates": 1,
                        "binding_rule": "scanned_pdf_structure_sequence_fallback",
                    },
                    best_p,
                )
            )
        no_binding = []
        unbound_pages = []
        all_blocks = [
            {"cpd": b["cpd"], "cpd_num": b["cpd_num"], "prefix": b["prefix"]}
            for b in final_bindings
        ]
        detected_style = "structure_sequence_fallback"
        logger.info(f"   ✅ 结构序列兜底绑定完成: {len(final_bindings)} 个结构")
        goto_save = True
    else:
        goto_save = False

    logger.info("🎯 对每个化合物应用选择算法...")

    if not goto_save:
        final_bindings: List[Dict] = list(seeded_bindings)
        no_binding: List[str] = []
        unbound_pages: List[Dict] = []
        seeded_bases = {_binding_base_num(b) for b in seeded_bindings}
        seeded_bases.discard(None)
    else:
        seeded_bases = set()

    for i, block in enumerate([] if goto_save else all_blocks):
        cpd = block["cpd"]
        block_base = _base_cpd_num(cpd)
        if block_base in seeded_bases:
            continue
        cpd_page = block["page_no"]
        cpd_y0 = block["y0"]

        start_page = cpd_page
        start_y0 = cpd_y0
        end_page = None
        end_y0 = None

        if i < len(all_blocks) - 1:
            next_block = all_blocks[i + 1]
            if next_block["prefix"] == block["prefix"]:
                end_page = next_block["page_no"]
                end_y0 = next_block["y0"]

        # 筛选候选结构
        candidate_structs: List[Dict] = []
        for p in processed_structures:
            in_range = False

            if end_page is None:
                if p["page_no"] > start_page:
                    in_range = True
                elif p["page_no"] == start_page and p["y0"] >= start_y0:
                    in_range = True
            else:
                if start_page == end_page:
                    if p["page_no"] == start_page and start_y0 <= p["y0"] < end_y0:
                        in_range = True
                else:
                    if p["page_no"] == start_page and p["y0"] >= start_y0:
                        in_range = True
                    elif start_page < p["page_no"] < end_page:
                        in_range = True
                    elif p["page_no"] == end_page and p["y0"] < end_y0:
                        in_range = True

            if in_range:
                candidate_structs.append(p)

        # 回退策略：heading 下方无候选 → 搜索上方 → 搜索前页
        if not candidate_structs:
            bound_struct_ids = set(b["structure_id"] for b in final_bindings)

            # 同页上方
            above_structs = [
                p
                for p in processed_structures
                if p["page_no"] == start_page
                and p["y0"] < start_y0
                and p["id"] not in bound_struct_ids
            ]
            if above_structs:
                above_structs.sort(key=lambda x: x["y0"], reverse=True)
                candidate_structs = above_structs
                logger.info(
                    f"   🔄 {cpd} (p{cpd_page}): heading下方无候选，"
                    f"回退搜索上方 {len(candidate_structs)} 个结构"
                )

            # 前页底部
            if not candidate_structs and start_page > 1:
                prev_page = start_page - 1
                prev_structs = [
                    p
                    for p in processed_structures
                    if p["page_no"] == prev_page and p["id"] not in bound_struct_ids
                ]
                if prev_structs:
                    prev_structs.sort(key=lambda x: x["y0"], reverse=True)
                    candidate_structs = prev_structs[:3]
                    logger.info(
                        f"   🔄 {cpd} (p{cpd_page}): 回退搜索前页p{prev_page} "
                        f"{len(candidate_structs)} 个结构"
                    )

            # Scanned Chinese examples may have the title at the bottom of one
            # page and the product structure at the top of the next page.
            if not candidate_structs and block_base in {
                _base_cpd_num(c) for c in active_cpds
            }:
                for near_page in (start_page + 1, start_page + 2):
                    if block_base and not _page_has_product_context(
                        pages_text, near_page, block_base
                    ):
                        continue
                    near_structs = [
                        p
                        for p in processed_structures
                        if p["page_no"] == near_page and p["id"] not in bound_struct_ids
                    ]
                    if not near_structs:
                        continue
                    near_structs.sort(key=lambda x: (x["y0"], x["x0"]))
                    candidate_structs = near_structs[:3]
                    logger.info(
                        f"   🔄 {cpd} (p{cpd_page}): 活性标题跨页，"
                        f"回退搜索后页p{near_page} {len(candidate_structs)} 个结构"
                    )
                    break

        # 应用选择算法
        if candidate_structs:
            best_p = _select_best_structure_v4(
                candidate_structs, config, heading_page=start_page
            )
            if best_p:
                final_bindings.append(
                    _attach_structure_geometry(
                        {
                            "cpd": cpd,
                            "cpd_num": block["cpd_num"],
                            "prefix": block["prefix"],
                            "structure_id": best_p["id"],
                            "page_no": best_p["page_no"],
                            "structure_index": best_p["idx"],
                            "struct_x0": best_p["x0"],
                            "struct_y0": best_p["y0"],
                            "image_path": best_p["image_path"],
                            "candidates": len(candidate_structs),
                            "binding_rule": "heading_range_fallback",
                        },
                        best_p,
                    )
                )
            else:
                no_binding.append(cpd)
                unbound_pages.append(
                    {"cpd": cpd, "page": cpd_page, "reason": "no_best"}
                )
        else:
            no_binding.append(cpd)
            unbound_pages.append(
                {"cpd": cpd, "page": cpd_page, "reason": "no_candidates"}
            )
            logger.warning(f"   ⚠️ {cpd} (p{cpd_page}): 无候选结构")

    logger.info(f"   ✅ 最终绑定了 {len(final_bindings)} 个化合物")

    if no_binding:
        logger.info(f"   ⚠️ {len(no_binding)} 个未绑定: {no_binding}")

    final_bindings = _annotate_bindings_with_visible_labels(
        final_bindings, visible_label_cache
    )

    if seeded_bindings and not goto_save:
        before_merge = len(final_bindings)
        seeded_bindings = _annotate_bindings_with_visible_labels(
            seeded_bindings, visible_label_cache
        )
        fallback_bindings = [b for b in final_bindings if b not in seeded_bindings]
        final_bindings = _merge_binding_candidates(
            seeded_bindings, fallback_bindings, active_cpds=active_cpds
        )
        logger.info(
            f"   🔗 OCR强绑定 + heading补漏合并: {before_merge} → {len(final_bindings)} 个化合物"
        )

    cpd_counts: Dict[str, int] = {}

    for binding in final_bindings:
        cpd = binding["cpd"]
        cpd_counts[cpd] = cpd_counts.get(cpd, 0) + 1

    cpd_suffix: Dict[str, int] = {}

    for binding in final_bindings:
        cpd = binding["cpd"]
        if cpd_counts[cpd] > 1:
            cpd_suffix[cpd] = cpd_suffix.get(cpd, 0) + 1
            suffix = cpd_suffix[cpd]
            # Update all name fields
            binding["cpd"] = f"{cpd}-{suffix}"

            binding["example_id"] = f"{binding.get('example_id', cpd)}-{suffix}"

    renamed = sum(1 for v in cpd_counts.values() if v > 1)

    if renamed:
        logger.info(
            f"   🏷 对 {renamed} 个重复化合物名添加后缀: "
            f"{[f'{k}({v}x)' for k, v in cpd_counts.items() if v > 1]}"
        )

    if not include_intermediates:
        final_bindings = _filter_examples_only(final_bindings)
        all_blocks = [b for b in all_blocks if not _is_intermediate(b)]
    return BindingSelection(
        final_bindings,
        all_blocks,
        detected_style,
        no_binding,
        unbound_pages,
        visible_label_cache,
        visual_grid_bindings,
    )
