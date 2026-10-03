"""Conservative missing-candidate completion strategies."""

from __future__ import annotations

import logging
import re
from typing import (
    Any,
    Dict,
    List,
    Optional,
    Tuple,
)

from .binding_candidates import (
    _active_ordered_bindings,
    _binding_sort_key,
    _build_binding_from_structure,
    _is_contextual_final_visual_candidate,
    _is_low_internal_label_in_multi_visible_crop,
    _normalise_binding_to_compound,
    _strict_single_visible_candidate_for_missing,
    _visible_label_conflict_rank,
)
from .binding_geometry import (
    _attach_structure_geometry,
    _best_table_structure_for_row_label,
    _group_structures_by_row,
    _is_complete_visible_product_module,
    _is_probable_table_structure,
    _right_complete_product_on_same_row,
    _route_product_structures_from_page,
    _row_for_structure,
    _structure_geometry,
    _structure_row_bounds,
    _visual_module_score,
)
from .binding_labels import (
    _VISIBLE_LABEL_SOURCE_RANK,
    _active_label_keys,
    _base_cpd_num,
    _binding_label_key,
    _cpd_label_key,
    _normalise_compound_label,
    _passes_exact_visual_label_guard,
    _route_title_numbers_from_text,
    _strict_visible_label_keys_for_binding,
)
from .binding_observations import (
    _annotate_bindings_with_visible_labels,
    _contextual_visible_label_candidates,
    _normalise_ocr_line_map,
    _normalise_visible_cache_item,
)
from .binding_tables import (
    _extract_table_row_numbers_from_lines,
    _is_structure_table_layout,
)

logger = logging.getLogger(__name__)


def _restore_safe_missing_active_bindings(
    final_bindings: List[Dict],
    candidate_bindings: List[Dict],
    processed_structures: List[Dict],
    active_cpds: List[str],
    visible_label_cache: Optional[Dict[str, Dict]] = None,
) -> List[Dict]:
    """Restore missing active rows only from product-like table/heading candidates."""
    if not active_cpds or not candidate_bindings:
        return final_bindings

    active_keys = _active_label_keys(active_cpds)
    final_bindings = _annotate_bindings_with_visible_labels(
        final_bindings, visible_label_cache
    )
    present_keys = {_binding_label_key(binding) for binding in final_bindings}
    missing_keys = active_keys - present_keys
    if not missing_keys:
        return final_bindings

    struct_by_id = {
        str(struct.get("id") or ""): struct for struct in processed_structures
    }
    page_structs_by_no: Dict[int, List[Dict]] = {}
    for struct in processed_structures:
        page_structs_by_no.setdefault(int(struct.get("page_no") or 0), []).append(
            struct
        )
    rows_by_page = {
        page_no: _group_structures_by_row(page_structs, y_threshold=55.0)
        for page_no, page_structs in page_structs_by_no.items()
    }

    restore_rules = {
        "structure_table_row_order",
        "structure_table_row_order_inferred",
        "structure_table_row_order_corrected",
        "heading_range_fallback",
    }
    additions: List[Dict] = []
    used_structures = {
        str(binding.get("source_structure_id") or binding.get("structure_id") or "")
        for binding in final_bindings
    }
    for binding in candidate_bindings:
        key = _binding_label_key(binding)
        if key not in missing_keys:
            continue
        rule = str(binding.get("binding_rule") or "")
        if rule not in restore_rules:
            continue
        sid = str(
            binding.get("source_structure_id") or binding.get("structure_id") or ""
        )
        if not sid or sid in used_structures:
            continue
        struct = struct_by_id.get(sid)
        if not struct:
            continue
        geom = _structure_geometry(struct)
        page_no = int(struct.get("page_no") or 0)
        table_like = _is_probable_table_structure(
            struct, page_structs_by_no.get(page_no)
        )
        heading_like = (
            rule == "heading_range_fallback"
            and _is_complete_visible_product_module(struct)
        )
        if not table_like and not heading_like:
            continue
        if geom["struct_area"] < 6500:
            continue

        replacement_struct = _right_complete_product_on_same_row(struct, rows_by_page)
        if (
            replacement_struct
            and str(replacement_struct.get("id") or "") not in used_structures
        ):
            struct = replacement_struct
            sid = str(struct.get("id") or "")
            rule = "heading_row_right_product_recovery"
            geom = _structure_geometry(struct)

        item = _normalise_binding_to_compound(dict(binding), key)
        item["structure_id"] = sid
        item["source_structure_id"] = sid
        item["page_no"] = struct["page_no"]
        item["structure_index"] = struct["idx"]
        item["struct_x0"] = struct["x0"]
        item["struct_y0"] = struct["y0"]
        item["image_path"] = struct["image_path"]
        _attach_structure_geometry(item, struct)
        item["binding_rule"] = rule
        item = _annotate_bindings_with_visible_labels([item], visible_label_cache)[0]
        right_product_recovery = rule == "heading_row_right_product_recovery"
        if (
            _visible_label_conflict_rank(item, active_keys) >= 5
            and key not in _strict_visible_label_keys_for_binding(item)
            and not right_product_recovery
        ):
            continue
        if _is_low_internal_label_in_multi_visible_crop(item):
            continue
        item["restored_missing_active"] = True
        additions.append(item)
        used_structures.add(sid)
        missing_keys.discard(key)

    if additions:
        logger.info(
            "   表格/标题完整结构安全回填缺失活性编号: +%d (%s)",
            len(additions),
            ", ".join(_binding_label_key(item) for item in additions),
        )
    return _active_ordered_bindings([*final_bindings, *additions], active_cpds)


def _fill_missing_from_cmpd_overview_tables(
    final_bindings: List[Dict],
    processed_structures: List[Dict],
    pages_text: Dict[int, str],
    active_cpds: List[str],
    ocr_line_map: Optional[Dict[int, List[Any]]] = None,
) -> List[Dict]:
    """Recover active structures from Cmpd No./Structure overview grids."""
    if not active_cpds:
        return final_bindings

    active_keys = _active_label_keys(active_cpds)
    present_keys = {_binding_label_key(binding) for binding in final_bindings}
    missing_keys = active_keys - present_keys
    if not missing_keys:
        return final_bindings

    used_structures = {
        str(binding.get("source_structure_id") or binding.get("structure_id") or "")
        for binding in final_bindings
    }
    additions: List[Dict] = []
    by_page: Dict[int, List[Dict]] = {}
    for struct in processed_structures:
        by_page.setdefault(int(struct.get("page_no") or 0), []).append(struct)
    lines_by_page = _normalise_ocr_line_map(ocr_line_map)

    for page_idx, text in sorted((pages_text or {}).items()):
        page_text = str(text or "")
        overview_like = bool(
            re.search(r"Cmpd\s*No\.?\s+Structure", page_text, re.IGNORECASE)
        )
        similar_like = bool(
            re.search(
                r"(?:Examples?|Compounds?)\s+\d{1,3}[^\n]{0,120}(?:prepared|following|similar procedure)",
                page_text,
                re.IGNORECASE,
            )
        )
        if not overview_like and not similar_like:
            continue
        page_no = int(page_idx) + 1
        page_structs = sorted(
            by_page.get(page_no, []),
            key=lambda item: (float(item.get("y0") or 0), float(item.get("x0") or 0)),
        )
        page_lines = lines_by_page.get(page_no - 1) or []
        active_bases = {_base_cpd_num(key) for key in missing_keys}
        active_bases.discard(None)
        row_entries = _extract_table_row_numbers_from_lines(
            page_lines, active_bases, page_structs
        )
        if not row_entries:
            # Do not recover from flat prose order. Overview/table recovery is
            # only safe when OCR gives the left compound-number column.
            continue
        struct_rows = _group_structures_by_row(
            [s for s in page_structs if str(s.get("id") or "") not in used_structures],
            y_threshold=55.0,
        )
        if not struct_rows:
            continue
        row_available = list(enumerate(struct_rows))
        for num, y0, _text in row_entries:
            key = _cpd_label_key(str(num))
            if key not in missing_keys:
                continue
            if not row_available:
                break
            best_idx, best_row = min(
                row_available,
                key=lambda pair: abs(float(y0) - _structure_row_bounds(pair[1])[2]),
            )
            if abs(float(y0) - _structure_row_bounds(best_row)[2]) > 95.0:
                continue
            struct = _best_table_structure_for_row_label(best_row, y0, page_structs)
            if not struct or not _is_complete_visible_product_module(struct):
                row_available = [item for item in row_available if item[0] != best_idx]
                continue
            sid = str(struct.get("id") or "")
            if sid in used_structures:
                row_available = [item for item in row_available if item[0] != best_idx]
                continue
            binding = _build_binding_from_structure(struct, key)
            binding["binding_rule"] = "cmpd_overview_table_order"
            binding["overview_table_recovery"] = True
            additions.append(binding)
            used_structures.add(sid)
            missing_keys.discard(key)
            row_available = [item for item in row_available if item[0] != best_idx]
        if not missing_keys:
            break

    if additions:
        logger.info(
            "   Cmpd No./Structure总览表补齐缺失活性结构: +%d (%s)",
            len(additions),
            ", ".join(_binding_label_key(item) for item in additions),
        )
    return _active_ordered_bindings([*final_bindings, *additions], active_cpds)


def _fill_missing_from_route_title_rows(
    final_bindings: List[Dict],
    processed_structures: List[Dict],
    pages_text: Dict[int, str],
    active_cpds: List[str],
    visible_label_cache: Optional[Dict[str, Dict]] = None,
    ocr_line_map: Optional[Dict[int, List[Any]]] = None,
) -> List[Dict]:
    """Recover missing active examples from route-title rows.

    Some OCR PDFs flatten heading coordinates to y=0, but the visual page remains
    regular: "Example N:" titles appear in text order and each reaction row ends
    with the final product on the right. Use that layout only for missing active
    rows and never on true structure-table pages.
    """
    if not active_cpds:
        return final_bindings
    active_keys = _active_label_keys(active_cpds)
    present_keys = {_binding_label_key(binding) for binding in final_bindings}
    missing_keys = active_keys - present_keys
    if not missing_keys:
        return final_bindings

    used_structures = {
        str(binding.get("source_structure_id") or binding.get("structure_id") or "")
        for binding in final_bindings
    }
    by_page: Dict[int, List[Dict]] = {}
    for struct in processed_structures:
        by_page.setdefault(int(struct.get("page_no") or 0), []).append(struct)
    lines_by_page = _normalise_ocr_line_map(ocr_line_map)

    additions: List[Dict] = []
    for page_idx, text in sorted((pages_text or {}).items()):
        page_no = int(page_idx) + 1
        page_text = str(text or "")
        title_keys = _route_title_numbers_from_text(page_text)
        if not any(key in missing_keys for key in title_keys):
            continue
        page_structs = sorted(
            by_page.get(page_no, []),
            key=lambda item: (float(item.get("y0") or 0), float(item.get("x0") or 0)),
        )
        if not page_structs:
            continue
        page_lines = lines_by_page.get(page_no - 1) or []
        active_bases = {_base_cpd_num(key) for key in active_keys}
        active_bases.discard(None)
        if _is_structure_table_layout(
            page_structs, page_text, ocr_lines=page_lines, active_bases=active_bases
        ):
            continue
        products = [
            struct
            for struct in _route_product_structures_from_page(page_structs)
            if str(struct.get("id") or "") not in used_structures
        ]
        if not products:
            continue
        # A page can begin with the previous example's scheme and only later show
        # the current "Example N:" title. If OCR sees fewer titles than route
        # rows, align the visible titles to the trailing product rows.
        product_offset = max(0, len(products) - len(title_keys))
        for idx, key in enumerate(title_keys):
            product_idx = product_offset + idx
            if key not in missing_keys or product_idx >= len(products):
                continue
            struct = products[product_idx]
            sid = str(struct.get("id") or "")
            if sid in used_structures:
                continue
            binding = _build_binding_from_structure(struct, key)
            binding["binding_rule"] = "route_title_row_right_product"
            binding["route_title_recovery"] = True
            binding = _annotate_bindings_with_visible_labels(
                [binding], visible_label_cache
            )[0]
            additions.append(binding)
            used_structures.add(sid)
            missing_keys.discard(key)
        if not missing_keys:
            break

    if additions:
        logger.info(
            "   反应路线标题行右侧产物补齐缺失活性结构: +%d (%s)",
            len(additions),
            ", ".join(_binding_label_key(item) for item in additions),
        )
    return _active_ordered_bindings([*final_bindings, *additions], active_cpds)


def _fill_missing_active_from_visible_cache(
    final_bindings: List[Dict],
    processed_structures: List[Dict],
    active_cpds: List[str],
    pages_text: Dict[int, str],
    visible_label_cache: Optional[Dict[str, Dict]],
    ocr_line_map: Optional[Dict[int, List[Any]]] = None,
) -> List[Dict]:
    """Recover missing active compounds from strict visual labels.

    This runs after normal binding/repair. It does not invent non-active rows:
    a structure can be used only when its cached visible label is an active
    compound number and nearby product context confirms that same number.
    """
    if not active_cpds or not visible_label_cache:
        return final_bindings
    active_keys = _active_label_keys(active_cpds)
    used_keys = {_binding_label_key(binding) for binding in final_bindings}
    used_keys.discard("")
    used_structures = {
        str(binding.get("source_structure_id") or binding.get("structure_id") or "")
        for binding in final_bindings
    }
    missing_keys = active_keys - used_keys
    if not missing_keys:
        return final_bindings

    struct_by_id = {
        str(struct.get("id") or ""): struct for struct in processed_structures
    }
    page_structs_by_no: Dict[int, List[Dict]] = {}
    for struct in processed_structures:
        page_structs_by_no.setdefault(int(struct.get("page_no") or 0), []).append(
            struct
        )
    rows_by_page = {
        page_no: _group_structures_by_row(page_structs, y_threshold=55.0)
        for page_no, page_structs in page_structs_by_no.items()
    }
    lines_by_page = _normalise_ocr_line_map(ocr_line_map)
    candidates_by_key: Dict[str, List[Tuple[Tuple[int, int, int, int, int], Dict]]] = {}
    for sid, cache_item in (visible_label_cache or {}).items():
        sid = str(sid)
        if sid in used_structures:
            continue
        struct = struct_by_id.get(sid)
        if not struct:
            continue
        visual_candidates = _contextual_visible_label_candidates(
            struct,
            _normalise_visible_cache_item(cache_item),
            missing_keys,
            pages_text,
            max_context_distance=1,
            lines_by_page=lines_by_page,
            row=_row_for_structure(struct, rows_by_page),
        )
        if not visual_candidates:
            visual_candidate = _strict_single_visible_candidate_for_missing(
                struct,
                _normalise_visible_cache_item(cache_item),
                missing_keys,
                active_keys,
                pages_text=pages_text,
                lines_by_page=lines_by_page,
                row=_row_for_structure(struct, rows_by_page),
            )
            if visual_candidate:
                visual_candidates = [visual_candidate]
        if not visual_candidates:
            continue
        width = max(0.0, float(struct.get("x1") or 0) - float(struct.get("x0") or 0))
        height = max(0.0, float(struct.get("y1") or 0) - float(struct.get("y0") or 0))
        area = int(width * height)
        for visual_candidate in visual_candidates:
            label = _normalise_compound_label(str(visual_candidate.get("label") or ""))
            key = _cpd_label_key(label)
            if not key or key not in missing_keys:
                continue
            ok_exact, exact_label = _passes_exact_visual_label_guard(
                struct,
                key,
                lines_by_page,
                row=_row_for_structure(struct, rows_by_page),
            )
            if not ok_exact:
                continue
            if not _is_contextual_final_visual_candidate(struct, visual_candidate):
                continue
            binding = _build_binding_from_structure(struct, key)
            binding["binding_rule"] = "direct_structure_label"
            binding["visible_label"] = label
            binding["visual_label_source"] = "cache_fill"
            binding["visible_label_crop_source"] = str(
                visual_candidate.get("source") or ""
            )
            binding["visible_label_multi_candidate"] = bool(
                visual_candidate.get("multi_label_crop")
            )
            binding["product_context_nearby"] = True
            binding["product_context_distance"] = int(
                visual_candidate.get("product_context_distance") or 0
            )
            if exact_label:
                binding["nearby_exact_product_label"] = exact_label
            binding["struct_width"] = width
            binding["struct_height"] = height
            binding["struct_area"] = width * height
            source_rank = _VISIBLE_LABEL_SOURCE_RANK.get(
                str(visual_candidate.get("source") or ""), 99
            )
            score = (
                int(binding["product_context_distance"]),
                source_rank,
                1 if bool(visual_candidate.get("multi_label_crop")) else 0,
                _visual_module_score(struct)[0],
                -area,
            )
            candidates_by_key.setdefault(key, []).append((score, binding))

    additions: List[Dict] = []
    for key, candidates in candidates_by_key.items():
        candidates.sort(key=lambda item: item[0])
        additions.append(candidates[0][1])

    if additions:
        logger.info(
            "   👁 可见编号缓存补齐活性结构: +%d (%s)",
            len(additions),
            ", ".join(
                str(_binding_label_key(item))
                for item in sorted(additions, key=_binding_sort_key)
            ),
        )
    return _active_ordered_bindings([*final_bindings, *additions], active_cpds)
