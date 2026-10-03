"""Conflict arbitration and fail-closed final selection."""

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

from patent_sar_extractor.core.pipeline_rules import annotate_binding_accuracy

from .binding_candidates import (
    _active_ordered_bindings,
    _build_binding_from_structure,
    _derive_right_product_binding,
    _final_structure_binding_quality,
    _has_exact_visual_product_evidence,
    _is_contextual_final_visual_candidate,
    _is_low_internal_label_in_multi_visible_crop,
    _is_weak_direct_visual_binding,
    _visible_label_conflict_rank,
    _visual_binding_priority,
)
from .binding_geometry import (
    _group_structures_by_row,
    _is_complete_visible_product_module,
    _is_ocsr_single_molecule_source,
    _is_probable_table_structure,
    _right_complete_product_on_same_row,
    _row_for_structure,
    _structure_geometry,
    _visual_module_score,
)
from .binding_labels import (
    _STRICT_VISIBLE_LABEL_SOURCES,
    _VISIBLE_LABEL_SOURCE_RANK,
    _active_label_keys,
    _base_cpd_num,
    _binding_label_key,
    _cpd_label_key,
    _nearby_ocr_label_kind,
    _normalise_compound_label,
    _passes_exact_visual_label_guard,
    _product_context_distance,
    _strict_visible_label_keys_for_binding,
    _visible_label_keys_for_binding,
)
from .binding_observations import (
    _annotate_bindings_with_visible_labels,
    _annotate_isotope_label_evidence,
    _contextual_visible_label_candidates,
    _labels_from_visible_cache_item,
    _normalise_ocr_line_map,
    _normalise_visible_cache_item,
)

logger = logging.getLogger(__name__)


def _repair_fallback_bindings_with_visual_modules(
    final_bindings: List[Dict],
    visual_bindings: List[Dict],
    active_cpds: List[str],
    output_dir: str = "",
) -> List[Dict]:
    """Replace only missing/prose fallback bindings with visual module matches."""
    if not active_cpds or not visual_bindings:
        return final_bindings

    active_keys = _active_label_keys(active_cpds)
    visual_by_key = {
        _binding_label_key(binding): binding
        for binding in sorted(
            visual_bindings, key=lambda b: _visual_binding_priority(b, active_keys)
        )
        if _binding_label_key(binding)
    }
    by_key = {
        _binding_label_key(binding): binding
        for binding in final_bindings
        if _binding_label_key(binding)
    }
    fallback_rules = {
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
    for cpd in active_cpds:
        key = _cpd_label_key(cpd)
        if not key or key not in visual_by_key:
            continue
        current = by_key.get(key)
        current_rule = str(current.get("binding_rule") or "") if current else ""
        current_area = float((current or {}).get("struct_area") or 0)
        current_w = float((current or {}).get("struct_width") or 0)
        current_h = float((current or {}).get("struct_height") or 0)
        current_is_weak_direct = current_rule == "direct_structure_label" and (
            current_area < 5000
            or (
                current_w > 0
                and current_h > 0
                and current_w / max(current_h, 1.0) > 5.5
            )
        )
        if current is None or current_rule in fallback_rules or current_is_weak_direct:
            by_key[key] = visual_by_key[key]

    if output_dir:
        for key, current in list(by_key.items()):
            if current is None:
                continue
            derived = _derive_right_product_binding(current, output_dir)
            if derived:
                by_key[key] = derived

    ordered = []
    for cpd in active_cpds:
        key = _cpd_label_key(cpd)
        if key in by_key:
            ordered.append(by_key[key])
    # Keep any non-active leftovers for callers that do not use active gating.
    ordered.extend(
        b for b in final_bindings if _binding_label_key(b) not in active_keys
    )
    return ordered


def _arbitrate_with_clean_standalone_visual_products(
    final_bindings: List[Dict],
    processed_structures: List[Dict],
    active_cpds: List[str],
    pages_text: Dict[int, str],
    visible_label_cache: Optional[Dict[str, Dict]],
    ocr_line_map: Optional[Dict[int, List[Any]]] = None,
) -> List[Dict]:
    """Replace route/intermediate winners with clean standalone product drawings.

    A strict OCR crop proves that a number is visible, but an intermediate such
    as ``80A`` may contain the parent ``80`` text as well. When another complete
    standalone crop has only the exact active label, that clean visual evidence
    is authoritative even if its label came from a wider OCR band.
    """
    if not final_bindings or not active_cpds or not visible_label_cache:
        return final_bindings

    active_keys = _active_label_keys(active_cpds)
    annotated = _annotate_bindings_with_visible_labels(
        final_bindings, visible_label_cache
    )
    by_key = {
        _binding_label_key(binding): dict(binding)
        for binding in annotated
        if _binding_label_key(binding)
    }
    struct_by_id = {
        str(struct.get("id") or ""): struct for struct in processed_structures
    }
    rows_by_page: Dict[int, List[List[Dict]]] = {}
    for page_no in sorted(
        {int(struct.get("page_no") or 0) for struct in processed_structures}
    ):
        rows_by_page[page_no] = _group_structures_by_row(
            [
                struct
                for struct in processed_structures
                if int(struct.get("page_no") or 0) == page_no
            ],
            y_threshold=55.0,
        )
    lines_by_page = _normalise_ocr_line_map(ocr_line_map)

    candidate_by_key: Dict[
        str, List[Tuple[Tuple[int, int, int, int, int, int], Dict]]
    ] = {}
    for sid, cache_item in (visible_label_cache or {}).items():
        struct = struct_by_id.get(str(sid))
        if not struct:
            continue
        candidates = _normalise_visible_cache_item(cache_item)
        label_keys = {
            _cpd_label_key(str(candidate.get("label") or ""))
            for candidate in candidates
            if _cpd_label_key(str(candidate.get("label") or ""))
        }
        if len(label_keys) != 1:
            continue
        key = next(iter(label_keys))
        if key not in active_keys or not _is_ocsr_single_molecule_source(struct):
            continue
        exact_candidates = [
            candidate
            for candidate in candidates
            if _cpd_label_key(str(candidate.get("label") or "")) == key
        ]
        if not exact_candidates:
            continue
        row = _row_for_structure(struct, rows_by_page)
        ok_exact, exact_label = _passes_exact_visual_label_guard(
            struct,
            key,
            lines_by_page,
            row=row,
        )
        if not ok_exact:
            continue
        source_candidate = min(
            exact_candidates,
            key=lambda candidate: _VISIBLE_LABEL_SOURCE_RANK.get(
                str(candidate.get("source") or ""), 99
            ),
        )
        context_distance = _product_context_distance(
            pages_text,
            int(struct.get("page_no") or 0),
            _base_cpd_num(key) or 0,
        )
        if context_distance > 1:
            continue
        binding = _build_binding_from_structure(struct, key)
        binding["binding_rule"] = "direct_structure_label"
        binding["visible_label"] = _normalise_compound_label(
            str(source_candidate.get("label") or key)
        )
        binding["visible_labels"] = _labels_from_visible_cache_item(cache_item)
        binding["visible_label_candidates"] = candidates
        binding["visual_label_source"] = "clean_standalone_arbitration"
        binding["visible_label_crop_source"] = str(source_candidate.get("source") or "")
        binding["visible_label_multi_candidate"] = False
        binding["product_context_nearby"] = context_distance <= 1
        binding["product_context_distance"] = int(context_distance)
        binding["ocsr_source_clean_single_molecule"] = True
        if exact_label:
            binding["nearby_exact_product_label"] = exact_label
        geom = _structure_geometry(struct)
        module_score = _visual_module_score(struct)
        score = (
            0 if context_distance <= 1 else 1,
            int(context_distance),
            module_score[0],
            module_score[1],
            _VISIBLE_LABEL_SOURCE_RANK.get(
                str(source_candidate.get("source") or ""), 99
            ),
            -int(geom["struct_area"]),
        )
        candidate_by_key.setdefault(key, []).append((score, binding))

    replacements = []
    for key, current in by_key.items():
        if key not in active_keys or key not in candidate_by_key:
            continue
        current_sid = str(
            current.get("source_structure_id") or current.get("structure_id") or ""
        )
        current_struct = struct_by_id.get(current_sid)
        current_labels = _visible_label_keys_for_binding(current)
        current_is_clean_complete = bool(
            current_struct
            and current_labels == {key}
            and _is_ocsr_single_molecule_source(current_struct)
            and not current.get("expanded_from_fragment")
        )
        if current_is_clean_complete:
            continue
        rule = str(current.get("binding_rule") or "")
        should_arbitrate = bool(
            current_labels - {key}
            or current.get("expanded_from_fragment")
            or rule == "direct_structure_label_merged_fragment"
            or (
                rule == "direct_structure_label"
                and current_struct
                and not _is_ocsr_single_molecule_source(current_struct)
            )
        )
        if not should_arbitrate:
            continue
        candidates = sorted(candidate_by_key[key], key=lambda item: item[0])
        candidate = next(
            (
                binding
                for _score, binding in candidates
                if str(binding.get("structure_id") or "") != current_sid
            ),
            None,
        )
        if not candidate:
            continue
        by_key[key] = candidate
        replacements.append(
            (key, current_sid, str(candidate.get("structure_id") or ""))
        )

    if replacements:
        logger.info(
            "   👁 干净独立终产物视觉仲裁: %d rows (%s)",
            len(replacements),
            ", ".join(f"{key}:{old}->{new}" for key, old, new in replacements),
        )
    return _active_ordered_bindings(list(by_key.values()), active_cpds)


def _replace_with_exact_visible_table_labels(
    final_bindings: List[Dict],
    processed_structures: List[Dict],
    active_cpds: List[str],
    visible_label_cache: Optional[Dict[str, Dict]],
    ocr_line_map: Optional[Dict[int, List[Any]]] = None,
) -> List[Dict]:
    """Prefer exact visible labels over row-order on mixed table/route pages."""
    if not final_bindings or not active_cpds or not visible_label_cache:
        return final_bindings

    active_keys = _active_label_keys(active_cpds)
    by_key = {
        _binding_label_key(binding): dict(binding)
        for binding in final_bindings
        if _binding_label_key(binding)
    }
    current_structures = {
        str(binding.get("source_structure_id") or binding.get("structure_id") or "")
        for binding in final_bindings
    }
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

    replacements = 0
    for sid, cache_item in (visible_label_cache or {}).items():
        sid = str(sid)
        struct = struct_by_id.get(sid)
        if not struct:
            continue
        page_no = int(struct.get("page_no") or 0)
        if not (
            _is_probable_table_structure(struct, page_structs_by_no.get(page_no))
            or _is_complete_visible_product_module(struct)
        ):
            continue
        labels = []
        for candidate in _normalise_visible_cache_item(cache_item):
            source = str(candidate.get("source") or "")
            if source not in _STRICT_VISIBLE_LABEL_SOURCES:
                continue
            label = _normalise_compound_label(str(candidate.get("label") or ""))
            key = _cpd_label_key(label)
            if key in active_keys:
                labels.append((key, label, source))
        exact_keys = {key for key, _label, _source in labels}
        if len(exact_keys) != 1:
            continue
        key, label, source = sorted(
            labels, key=lambda item: _VISIBLE_LABEL_SOURCE_RANK.get(item[2], 99)
        )[0]
        ok_exact, exact_label = _passes_exact_visual_label_guard(
            struct,
            key,
            lines_by_page,
            row=_row_for_structure(struct, rows_by_page),
        )
        if not ok_exact:
            continue
        current = by_key.get(key)
        if not current:
            continue
        current_rule = str(current.get("binding_rule") or "")
        current_sid = str(
            current.get("source_structure_id") or current.get("structure_id") or ""
        )
        current_area = float(current.get("struct_area") or 0)
        new_area = _structure_geometry(struct)["struct_area"]
        same_page = int(current.get("page_no") or 0) == page_no
        current_conflicts = key not in _visible_label_keys_for_binding(
            current
        ) and bool(_visible_label_keys_for_binding(current))
        should_replace = (
            current_rule
            in {
                "structure_table_row_order",
                "structure_table_row_order_inferred",
                "structure_table_row_order_corrected",
            }
            and same_page
            and sid != current_sid
            and (
                current_conflicts
                or new_area >= current_area * 0.80
                or (
                    _is_complete_visible_product_module(struct)
                    and key in exact_keys
                    and key not in _visible_label_keys_for_binding(current)
                )
            )
        )
        if not should_replace or sid in current_structures:
            continue
        binding = _build_binding_from_structure(struct, key)
        binding["binding_rule"] = "direct_structure_label"
        binding["visible_label"] = label
        binding["visual_label_source"] = "table_exact_visible"
        binding["visible_label_crop_source"] = source
        binding["visible_label_multi_candidate"] = False
        binding["visible_labels"] = _labels_from_visible_cache_item(cache_item)
        if exact_label:
            binding["nearby_exact_product_label"] = exact_label
        by_key[key] = binding
        current_structures.discard(current_sid)
        current_structures.add(sid)
        replacements += 1

    if replacements:
        logger.info("   👁 表格精确可见编号替换行序绑定: %d rows", replacements)

    ordered: List[Dict] = []
    for cpd in active_cpds:
        key = _cpd_label_key(cpd)
        if key in by_key:
            ordered.append(by_key[key])
    return ordered


def _repair_conflicting_bindings_from_visible_cache(
    final_bindings: List[Dict],
    processed_structures: List[Dict],
    active_cpds: List[str],
    pages_text: Dict[int, str],
    visible_label_cache: Optional[Dict[str, Dict]],
    ocr_line_map: Optional[Dict[int, List[Any]]] = None,
) -> List[Dict]:
    """Replace weak/conflicting winners with strict visual-label matches."""
    if not active_cpds or not visible_label_cache:
        return final_bindings

    active_keys = _active_label_keys(active_cpds)
    by_key = {
        _binding_label_key(binding): binding
        for binding in _annotate_bindings_with_visible_labels(
            final_bindings, visible_label_cache
        )
        if _binding_label_key(binding)
    }
    target_keys: set[str] = set()
    weak_rules = {
        "heading_range_fallback",
        "product_section_context",
        "ocr_numeric_structure_label",
        "ocr_bare_numeric_product_label",
        "paired_route_product_row_order",
        "triplet_split_row_structure_order",
        "split_reaction_product_label",
        "dense_scheme_final_product",
    }
    for key, binding in by_key.items():
        if key not in active_keys:
            continue
        rule = str(binding.get("binding_rule") or "")
        if rule in {
            "structure_table_row_order",
            "structure_table_row_order_inferred",
            "structure_table_row_order_corrected",
        }:
            # Table row IDs are usually in the left text column, not in the
            # drawing crop. Internal atom/reagent labels such as "1", "2",
            # "7", or "11" must not cause an otherwise valid table row to be
            # replaced by a different active compound.
            geom = _structure_geometry(binding)
            if geom["struct_area"] >= 6500:
                continue
        if (
            _visible_label_conflict_rank(binding, active_keys) >= 5
            or rule in weak_rules
            or _is_weak_direct_visual_binding(binding)
        ):
            target_keys.add(key)
        elif (
            rule == "direct_structure_label"
            and key in _visible_label_keys_for_binding(binding)
            and key not in _strict_visible_label_keys_for_binding(binding)
        ):
            target_keys.add(key)
    if not target_keys:
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
        struct = struct_by_id.get(str(sid))
        if not struct:
            continue
        raw_candidates = _normalise_visible_cache_item(cache_item)
        visual_candidates = []
        for candidate in raw_candidates:
            source = str(candidate.get("source") or "")
            if source not in _STRICT_VISIBLE_LABEL_SOURCES:
                continue
            label = _normalise_compound_label(str(candidate.get("label") or ""))
            key = _cpd_label_key(label)
            if key not in target_keys:
                continue
            visual_candidates.append(
                {
                    "label": label,
                    "label_key": key,
                    "source": source,
                    "product_context_distance": _product_context_distance(
                        pages_text,
                        int(struct.get("page_no") or 0),
                        _base_cpd_num(label) or 0,
                    ),
                    "multi_label_crop": len(
                        {
                            str(c.get("label") or "").strip()
                            for c in raw_candidates
                            if c.get("label")
                        }
                    )
                    > 1,
                }
            )
        if not visual_candidates:
            continue
        geometry = _structure_geometry(struct)
        if geometry["struct_area"] < 1800:
            continue
        for visual_candidate in visual_candidates:
            key = _cpd_label_key(str(visual_candidate.get("label") or ""))
            if key not in target_keys:
                continue
            nearby_label_kind = _nearby_ocr_label_kind(struct, key, lines_by_page)
            if nearby_label_kind == "racemic":
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
            binding["visible_label"] = str(visual_candidate.get("label") or key)
            binding["visual_label_source"] = "cache_repair"
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
            if nearby_label_kind:
                binding["nearby_ocr_label_kind"] = nearby_label_kind
            if exact_label:
                binding["nearby_exact_product_label"] = exact_label
            binding["visible_labels"] = _labels_from_visible_cache_item(cache_item)
            source_rank = _VISIBLE_LABEL_SOURCE_RANK.get(
                str(visual_candidate.get("source") or ""), 99
            )
            current = by_key.get(key, {})
            current_page = int((current or {}).get("page_no") or 0)
            page_delta = (
                abs(int(struct.get("page_no") or 0) - current_page)
                if current_page
                else 999
            )
            score = (
                source_rank,
                page_delta,
                int(binding["product_context_distance"]),
                1 if bool(visual_candidate.get("multi_label_crop")) else 0,
                _visual_module_score(struct)[0],
                -int(binding.get("struct_area") or 0),
            )
            candidates_by_key.setdefault(key, []).append((score, binding))

    replacements = 0
    for key, candidates in candidates_by_key.items():
        candidates.sort(key=lambda item: item[0])
        candidate = candidates[0][1]
        current = by_key.get(key)
        if current is None or _visual_binding_priority(
            candidate, active_keys
        ) < _visual_binding_priority(current, active_keys):
            by_key[key] = candidate
            replacements += 1
    if replacements:
        logger.info("   👁 可见编号冲突/弱绑定替换: %d rows", replacements)

    ordered: List[Dict] = []
    for cpd in active_cpds:
        key = _cpd_label_key(cpd)
        if key in by_key:
            ordered.append(by_key[key])
    return ordered


def _confirm_final_bindings_with_visible_cache(
    final_bindings: List[Dict],
    processed_structures: List[Dict],
    pages_text: Dict[int, str],
    visible_label_cache: Optional[Dict[str, Dict]],
    ocr_line_map: Optional[Dict[int, List[Any]]] = None,
) -> List[Dict]:
    """Annotate final active bindings with exact visual-label evidence.

    Heading/order fallbacks may still be correct, but when the chosen structure
    crop has a cached visible label matching the active compound, upgrade the
    row so downstream QA sees it as visually confirmed rather than prose-only.
    """
    if not final_bindings or not visible_label_cache:
        return final_bindings
    struct_by_id = {
        str(struct.get("id") or ""): struct for struct in processed_structures
    }
    lines_by_page = _normalise_ocr_line_map(ocr_line_map)
    rows_by_page = {
        page_no: _group_structures_by_row(page_structs, y_threshold=55.0)
        for page_no, page_structs in {
            page_no: [
                struct
                for struct in processed_structures
                if int(struct.get("page_no") or 0) == page_no
            ]
            for page_no in sorted(
                {int(struct.get("page_no") or 0) for struct in processed_structures}
            )
        }.items()
    }
    confirmed: List[Dict] = []
    upgraded = 0
    for binding in final_bindings:
        item = dict(binding)
        key = _binding_label_key(item)
        if not key:
            confirmed.append(item)
            continue
        sid = str(item.get("source_structure_id") or item.get("structure_id") or "")
        struct = struct_by_id.get(sid)
        if not struct:
            confirmed.append(item)
            continue
        visual_candidates = _contextual_visible_label_candidates(
            struct,
            _normalise_visible_cache_item((visible_label_cache or {}).get(sid)),
            {key},
            pages_text,
            max_context_distance=1,
            lines_by_page=lines_by_page,
            row=_row_for_structure(struct, rows_by_page),
        )
        if not visual_candidates:
            confirmed.append(item)
            continue
        visual_candidate = visual_candidates[0]
        if not _is_contextual_final_visual_candidate(struct, visual_candidate):
            confirmed.append(item)
            continue
        width = max(0.0, float(struct.get("x1") or 0) - float(struct.get("x0") or 0))
        height = max(0.0, float(struct.get("y1") or 0) - float(struct.get("y0") or 0))
        item["visible_labels"] = _labels_from_visible_cache_item(
            (visible_label_cache or {}).get(sid)
        )
        item["visible_label"] = str(visual_candidate.get("label") or key)
        item["visible_label_crop_source"] = str(visual_candidate.get("source") or "")
        item["visible_label_multi_candidate"] = bool(
            visual_candidate.get("multi_label_crop")
        )
        item["product_context_nearby"] = True
        item["product_context_distance"] = int(
            visual_candidate.get("product_context_distance") or 0
        )
        item["struct_width"] = width
        item["struct_height"] = height
        item["struct_area"] = width * height
        if str(item.get("binding_rule") or "") in {
            "heading_range_fallback",
            "product_section_context",
            "structure_table_row_order",
            "structure_table_row_order_inferred",
            "structure_table_row_order_corrected",
            "ocr_pair_heading_structure_order",
            "paired_route_product_row_order",
            "triplet_split_row_structure_order",
            "split_reaction_product_label",
            "ocr_numeric_structure_label",
            "ocr_bare_numeric_product_label",
            "heading_row_right_product_recovery",
            "same_row_right_product_repair",
            "route_title_row_right_product",
            "visual_grid_label",
        }:
            item["binding_rule"] = "direct_structure_label"
            item["visual_label_source"] = "cache_confirmed"
            upgraded += 1
        elif not item.get("visual_label_source"):
            item["visual_label_source"] = "cache_confirmed"
        confirmed.append(item)
    if upgraded:
        logger.info("   👁 最终绑定视觉确认升级: %d rows", upgraded)
    return confirmed


def _dedupe_final_bindings_by_structure(
    final_bindings: List[Dict],
    active_cpds: List[str],
    visible_label_cache: Optional[Dict[str, Dict]] = None,
) -> List[Dict]:
    """Prevent one structure image from being emitted for multiple active IDs."""
    if not final_bindings:
        return final_bindings
    active_keys = _active_label_keys(active_cpds)
    annotated = _annotate_bindings_with_visible_labels(
        final_bindings, visible_label_cache
    )
    best_by_structure: Dict[str, Dict] = {}
    duplicates = 0
    for binding in sorted(
        annotated, key=lambda b: _final_structure_binding_quality(b, active_keys)
    ):
        sid = str(
            binding.get("source_structure_id") or binding.get("structure_id") or ""
        )
        if not sid:
            continue
        if sid in best_by_structure:
            duplicates += 1
            continue
        best_by_structure[sid] = binding

    if not duplicates:
        return annotated

    winners = list(best_by_structure.values())
    logger.info("   🧯 最终结构去重: 移除 %d 个共享同一结构的低置信绑定", duplicates)
    return _active_ordered_bindings(winners, active_cpds)


def _drop_unsafe_final_fragment_bindings(
    final_bindings: List[Dict],
    active_cpds: List[str],
    visible_label_cache: Optional[Dict[str, Dict]] = None,
    processed_structures: Optional[List[Dict]] = None,
) -> List[Dict]:
    """Drop final rows that still look like small route fragments/intermediates."""
    if not final_bindings:
        return final_bindings
    active_keys = _active_label_keys(active_cpds)
    struct_by_id = {
        str(struct.get("id") or ""): struct for struct in (processed_structures or [])
    }
    rows_by_page: Dict[int, List[List[Dict]]] = {}
    if processed_structures:
        for page_no in sorted(
            {int(struct.get("page_no") or 0) for struct in processed_structures}
        ):
            rows_by_page[page_no] = _group_structures_by_row(
                [
                    struct
                    for struct in processed_structures
                    if int(struct.get("page_no") or 0) == page_no
                ],
                y_threshold=55.0,
            )
    kept: List[Dict] = []
    dropped: List[str] = []
    for binding in _annotate_bindings_with_visible_labels(
        final_bindings, visible_label_cache
    ):
        key = _binding_label_key(binding)
        strict_exact_visual = bool(
            key and key in _strict_visible_label_keys_for_binding(binding)
        )
        exact_visual_product = _has_exact_visual_product_evidence(binding, active_keys)
        rule = str(binding.get("binding_rule") or "")
        area = float(binding.get("struct_area") or 0)
        conflict_rank = _visible_label_conflict_rank(binding, active_keys)
        unsafe_small_fallback = (
            rule == "heading_range_fallback"
            and area < 6500
            and not exact_visual_product
        )
        unsafe_visible_conflict = (
            conflict_rank >= 5
            and key not in _strict_visible_label_keys_for_binding(binding)
        )
        unsafe_low_multi = _is_low_internal_label_in_multi_visible_crop(binding)
        table_row_rules = {
            "structure_table_row_order",
            "structure_table_row_order_inferred",
            "structure_table_row_order_corrected",
            "cmpd_overview_table_order",
        }
        strong_layout_product_rules = {
            "route_title_row_right_product",
            "heading_row_right_product_recovery",
            "same_row_right_product_repair",
            "cpd_letter_pair_row_order",
        }
        unsafe_table_visible_mismatch = False
        if rule in table_row_rules:
            visible_keys = _visible_label_keys_for_binding(binding)
            if (
                visible_keys
                and key not in visible_keys
                and not all(
                    re.fullmatch(r"\d{1,2}[A-Z]?", vkey or "") for vkey in visible_keys
                )
            ):
                unsafe_table_visible_mismatch = True

        unsafe_not_row_product = False
        if (
            rule in (table_row_rules | {"heading_range_fallback"})
            and processed_structures
        ):
            sid = str(
                binding.get("source_structure_id") or binding.get("structure_id") or ""
            )
            struct = struct_by_id.get(sid)
            if struct:
                if not (strict_exact_visual or exact_visual_product):
                    unsafe_not_row_product = (
                        _right_complete_product_on_same_row(
                            struct,
                            rows_by_page,
                            min_area_ratio=1.05,
                        )
                        is not None
                    )

        if (
            (unsafe_small_fallback and not strict_exact_visual)
            or (
                unsafe_visible_conflict
                and not (
                    rule in strong_layout_product_rules
                    and _is_complete_visible_product_module(binding)
                )
            )
            or (
                unsafe_low_multi
                and not (
                    rule in strong_layout_product_rules
                    and _is_complete_visible_product_module(binding)
                )
            )
            or (
                unsafe_table_visible_mismatch
                and not (strict_exact_visual or exact_visual_product)
            )
            or unsafe_not_row_product
        ):
            dropped.append(key or str(binding.get("cpd") or ""))
            continue
        kept.append(binding)
    if dropped:
        logger.info(
            "   🧯 剔除疑似中间体/反应片段终态绑定: %d (%s)",
            len(dropped),
            ", ".join(dropped[:20]),
        )
    return _active_ordered_bindings(kept, active_cpds)


def _drop_fail_closed_bindings(
    final_bindings: List[Dict],
    active_cpds: List[str],
    keep_review_bindings: bool = False,
) -> List[Dict]:
    """Hard gate: review-required/conflicting bindings must not enter OCSR."""
    if not final_bindings:
        return final_bindings
    kept: List[Dict] = []
    dropped: List[str] = []
    for binding in final_bindings:
        key = _binding_label_key(binding)
        if bool(binding.get("fail_closed")) or str(
            binding.get("accuracy_status") or ""
        ) not in {"", "confirmed"}:
            if keep_review_bindings:
                row = dict(binding)
                row["partial_review_candidate"] = True
                row.setdefault(
                    "review_reason",
                    "Retained for bootstrap partial export; strict acceptance still fails.",
                )
                kept.append(row)
                continue
            dropped.append(key or str(binding.get("cpd") or ""))
            continue
        kept.append(binding)
    if dropped:
        logger.info(
            "   🛑 fail-closed最终闸门: 移除 %d 个不可靠绑定 (%s)",
            len(dropped),
            ", ".join(dropped[:20]),
        )
    return _active_ordered_bindings(kept, active_cpds)


def finalize_binding_candidates(
    final_bindings: list[dict[str, Any]],
    active_cpds: list[str],
    profile: dict[str, Any],
    visible_label_cache: dict[str, dict[str, Any]],
    cached_line_map: dict[int, list[tuple[float, str]]],
) -> list[dict[str, Any]]:
    final_bindings = _annotate_bindings_with_visible_labels(
        final_bindings, visible_label_cache
    )
    final_bindings = _annotate_isotope_label_evidence(final_bindings, cached_line_map)
    final_bindings = [annotate_binding_accuracy(binding) for binding in final_bindings]
    keep_review_bindings = bool(profile.get("allow_review_bindings"))
    final_bindings = _drop_fail_closed_bindings(
        final_bindings,
        active_cpds,
        keep_review_bindings=keep_review_bindings,
    )
    final_bindings = [annotate_binding_accuracy(binding) for binding in final_bindings]
    return final_bindings
