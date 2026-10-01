"""Visual layout dispatch, never an alternative binder."""

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
)
from .binding_geometry import (
    _group_structures_by_row,
    _is_probable_table_structure,
    _row_for_structure,
    _visual_module_score,
)
from .binding_headings import (
    _filter_items_by_focus_windows,
)
from .binding_labels import (
    _FINAL_COMPOUND_LABEL_RE,
    _VISIBLE_LABEL_SOURCE_RANK,
    _VISUAL_LABEL_SOURCES,
    _active_label_keys,
    _base_cpd_num,
    _cpd_label_key,
    _int_or_default,
    _nearby_ocr_label_kind,
    _normalise_compound_label,
    _page_text_for_page_no,
    _passes_exact_visual_label_guard,
    _product_context_distance,
)
from .binding_observations import (
    _contextual_visible_label_candidates,
    _normalise_ocr_line_map,
    _normalise_visible_cache_item,
    _ocr_visible_label_band_from_page_image,
    _visible_label_candidates_for_structure,
    _visible_labels_for_structure,
)
from .binding_ocr import (
    _get_ocr_word_coords,
)
from .binding_products import (
    _extract_bare_product_label_bindings,
    _extract_cpd_letter_pair_product_bindings,
    _extract_first_dense_scheme_product,
    _extract_pair_heading_product_bindings,
    _extract_paired_route_product_bindings,
    _extract_product_section_bindings,
    _extract_split_reaction_bare_bindings,
    _extract_triplet_split_row_bindings,
)
from .binding_tables import (
    _extract_structure_table_bindings,
    _extract_structure_table_sequence_bindings,
    _is_structure_table_layout,
)

logger = logging.getLogger(__name__)


def _extract_visual_module_bindings(
    doc,
    processed_structures: List[Dict],
    active_cpds: List[str],
    pages_text: Dict[int, str],
    visible_label_cache: Optional[Dict[str, Dict]] = None,
    target_bases: Optional[set[int]] = None,
    ocr_line_map: Optional[Dict[int, List[Any]]] = None,
) -> List[Dict]:
    """Build high-confidence bindings from complete visual modules.

    This pass is intentionally separate from heading/prose fallbacks: it scans
    every structure module for a visible active compound number and only keeps
    candidates that also sit on a page with product context for that compound.
    It is used to repair missing/fallback bindings without disturbing existing
    strong direct-label bindings.
    """
    active_keys = _active_label_keys(active_cpds)
    active_bases = {_base_cpd_num(cpd) for cpd in active_cpds}
    active_bases.discard(None)
    if target_bases is not None:
        active_bases &= set(target_bases)
        active_keys = {
            key for key in active_keys if (_base_cpd_num(key) in active_bases)
        }
    if not active_keys:
        return []

    lines_by_page = _normalise_ocr_line_map(ocr_line_map)
    page_structs_by_no: Dict[int, List[Dict]] = {}
    for struct in processed_structures:
        page_structs_by_no.setdefault(int(struct.get("page_no") or 0), []).append(
            struct
        )
    rows_by_page = {
        page_no: _group_structures_by_row(page_structs, y_threshold=55.0)
        for page_no, page_structs in page_structs_by_no.items()
    }
    by_key: Dict[str, List[Dict]] = {}
    for struct in processed_structures:
        sid = str(struct.get("id") or "")
        cache_item = (visible_label_cache or {}).get(sid)
        if isinstance(cache_item, dict):
            visual_candidates = _contextual_visible_label_candidates(
                struct,
                _normalise_visible_cache_item(cache_item),
                active_keys,
                pages_text,
                max_context_distance=1,
                lines_by_page=lines_by_page,
                row=_row_for_structure(struct, rows_by_page),
            )
        else:
            labels = _ocr_visible_label_band_from_page_image(struct)
            if not any(_cpd_label_key(str(label)) in active_keys for label in labels):
                labels = [
                    *labels,
                    *_ocr_visible_label_band_from_page_image(struct, wide=True),
                ]
            visual_candidates = [
                {
                    "label": _normalise_compound_label(str(label)),
                    "source": "ocr",
                    "product_context_distance": _product_context_distance(
                        pages_text,
                        int(struct.get("page_no") or 0),
                        _base_cpd_num(str(label)) or 0,
                    )
                    if _cpd_label_key(str(label)) in active_keys
                    else 999,
                    "multi_label_crop": len(labels) > 1,
                }
                for label in labels
            ]
        for visual_candidate in visual_candidates:
            label = _normalise_compound_label(str(visual_candidate.get("label") or ""))
            label_key = _cpd_label_key(label)
            if not label_key or not re.fullmatch(
                r"[1-9]\d{0,2}[A-Z]?", label, re.IGNORECASE
            ):
                continue
            if label_key not in active_keys:
                continue
            nearby_label_kind = _nearby_ocr_label_kind(struct, label_key, lines_by_page)
            if nearby_label_kind == "racemic":
                continue
            ok_exact, exact_label = _passes_exact_visual_label_guard(
                struct,
                label_key,
                lines_by_page,
                row=_row_for_structure(struct, rows_by_page),
            )
            if not ok_exact:
                continue
            product_context_distance = _int_or_default(
                visual_candidate.get("product_context_distance"), 999
            )
            if product_context_distance > 1:
                continue
            if not _is_contextual_final_visual_candidate(struct, visual_candidate):
                continue
            width = max(
                0.0, float(struct.get("x1") or 0) - float(struct.get("x0") or 0)
            )
            height = max(
                0.0, float(struct.get("y1") or 0) - float(struct.get("y0") or 0)
            )
            if width * height < 2500:
                continue
            binding = _build_binding_from_structure(struct, label_key)
            binding["binding_rule"] = "direct_structure_label"
            binding["visible_label"] = str(label)
            binding["visual_label_source"] = "module"
            binding["visible_label_crop_source"] = str(
                visual_candidate.get("source") or ""
            )
            binding["visible_label_multi_candidate"] = bool(
                visual_candidate.get("multi_label_crop")
            )
            binding["product_context_nearby"] = True
            binding["product_context_distance"] = product_context_distance
            if nearby_label_kind:
                binding["nearby_ocr_label_kind"] = nearby_label_kind
            if exact_label:
                binding["nearby_exact_product_label"] = exact_label
            binding["struct_width"] = width
            binding["struct_height"] = height
            binding["struct_area"] = width * height
            by_key.setdefault(label_key, []).append(binding)

    selected: List[Dict] = []
    for _key, candidates in by_key.items():
        selected.append(
            min(
                candidates,
                key=lambda b: (
                    _int_or_default(b.get("product_context_distance"), 999),
                    _visual_module_score(
                        {
                            "x0": b.get("struct_x0"),
                            "x1": float(b.get("struct_x0") or 0)
                            + float(b.get("struct_width") or 0),
                            "y0": b.get("struct_y0"),
                            "y1": float(b.get("struct_y0") or 0)
                            + float(b.get("struct_height") or 0),
                            "idx": b.get("structure_index"),
                        }
                    ),
                ),
            )
        )
    return selected


def _active_visible_keys_for_struct(
    struct: Dict,
    visible_label_cache: Optional[Dict[str, Dict]],
    active_keys: set[str],
) -> List[Tuple[str, str]]:
    labels: List[Tuple[str, str]] = []
    for candidate in _normalise_visible_cache_item(
        (visible_label_cache or {}).get(str(struct.get("id") or ""))
    ):
        label = _normalise_compound_label(str(candidate.get("label") or ""))
        key = _cpd_label_key(label)
        source = str(candidate.get("source") or "")
        if key in active_keys and source in _VISUAL_LABEL_SOURCES:
            labels.append((key, source))
    return labels


def _visual_grid_primary_key(
    labels: List[Tuple[str, str]], page_min: int, page_max: int
) -> Optional[Tuple[str, str, bool]]:
    """Choose the printed product ID on dense structure-grid pages."""
    if not labels:
        return None
    ranked: List[Tuple[int, int, int, str, str]] = []
    for key, source in labels:
        base = _base_cpd_num(key)
        if base is None:
            continue
        in_page_sequence = page_min <= base <= page_max
        low_internal = base < page_min and base <= 30
        if not in_page_sequence and not low_internal:
            continue
        ranked.append(
            (
                0 if in_page_sequence else 3,
                0
                if source == "page_wide"
                else _VISIBLE_LABEL_SOURCE_RANK.get(source, 9),
                -base,
                key,
                source,
            )
        )
    if not ranked:
        return None
    ranked.sort()
    rank, _source_rank, _neg_base, key, source = ranked[0]
    if rank != 0:
        return None
    competing = [
        other_key
        for other_key, _source in labels
        if other_key != key
        and (other_base := _base_cpd_num(other_key)) is not None
        and page_min <= other_base <= page_max
    ]
    if competing:
        return None
    return key, source, len({label for label, _source in labels}) > 1


def _dominant_visual_grid_base_range(
    page_bases: List[int], structure_count: int
) -> Optional[Tuple[int, int, int]]:
    """Return the dense product-number run on a structure-grid page.

    Structure drawings often contain small substituent, reagent, or assay
    numbers. Dense grid pages, however, present final products as a compact
    sequence. Use the densest high-number window as the authoritative page
    range instead of letting a few internal labels stretch min/max.
    """
    bases = sorted({int(base) for base in page_bases if int(base) > 30})
    if len(bases) < 6:
        return None
    max_span = max(40, int(structure_count) * 2)
    best: Optional[Tuple[int, int, int, int, int]] = None
    for idx, start in enumerate(bases):
        window = [base for base in bases[idx:] if base - start <= max_span]
        if len(window) < 6:
            continue
        end = window[-1]
        count = len(window)
        span = max(1, end - start + 1)
        density = count / span
        high_count = sum(1 for base in window if base >= 100)
        score = (
            -count,
            -int(density * 1000),
            -high_count,
            span,
            start,
        )
        if best is None or score < best:
            best = score
    if best is None:
        return None
    _neg_count, _neg_density, _neg_high_count, _span, start = best
    count = -_neg_count
    end = max(base for base in bases if start <= base <= start + max_span)
    return start, end, count


def _visual_grid_sequence_order_bindings(
    page_structs: List[Dict],
    visible_items: List[Tuple[Dict, List[Tuple[str, str]]]],
    active_keys: set[str],
    page_min: int,
    page_max: int,
    page_label_count: int,
) -> List[Dict]:
    """Fill dense grid-page gaps from row/column order when visual anchors agree."""
    rows = _group_structures_by_row(page_structs, y_threshold=42.0)
    ordered_structs = [
        struct
        for row in rows
        for struct in sorted(row, key=lambda item: float(item.get("x0") or 0))
    ]
    if len(ordered_structs) < 6:
        return []

    label_map: Dict[str, List[Tuple[str, str]]] = {
        str(struct.get("id") or ""): labels for struct, labels in visible_items
    }
    direct_anchors: List[Tuple[int, int, Tuple[str, str, bool]]] = []
    for idx, struct in enumerate(ordered_structs):
        selected = _visual_grid_primary_key(
            label_map.get(str(struct.get("id") or ""), []),
            page_min,
            page_max,
        )
        if not selected:
            continue
        key, _source, _multi = selected
        base = _base_cpd_num(key)
        if base is not None:
            direct_anchors.append((idx, base, selected))
    if len(direct_anchors) < 6:
        return []

    offset_counts: Dict[int, int] = {}
    for position, base, _selected in direct_anchors:
        offset = base - position
        offset_counts[offset] = offset_counts.get(offset, 0) + 1
    sequence_start, anchor_count = sorted(
        offset_counts.items(),
        key=lambda item: (-item[1], abs(item[0] - page_min), item[0]),
    )[0]
    if anchor_count < max(6, int(len(direct_anchors) * 0.65)):
        return []
    selected_by_position = {
        position: selected
        for position, base, selected in direct_anchors
        if base - position == sequence_start
    }
    sequence_positions = [
        (idx, sequence_start + idx)
        for idx in range(len(ordered_structs))
        if page_min - 3 <= sequence_start + idx <= page_max + 3
        and str(sequence_start + idx) in active_keys
    ]
    if len(sequence_positions) < 6:
        return []

    additions: List[Dict] = []
    for idx, base in sequence_positions:
        key = str(base)
        struct = ordered_structs[idx]
        labels = label_map.get(str(struct.get("id") or ""), [])
        selected = selected_by_position.get(idx)
        if selected:
            label, source, multi_label = selected
            binding_rule = "visual_grid_label"
        else:
            label = key
            source = "visual_grid_sequence"
            multi_label = len({label_key for label_key, _source in labels}) > 1
            binding_rule = "visual_grid_sequence_order"
        binding = _build_binding_from_structure(struct, key)
        binding["binding_rule"] = binding_rule
        binding["visible_label"] = label
        binding["visual_label_source"] = (
            "visual_grid"
            if binding_rule == "visual_grid_label"
            else "visual_grid_sequence"
        )
        binding["visible_label_crop_source"] = source
        binding["visible_label_multi_candidate"] = (
            False if binding_rule == "visual_grid_label" else bool(multi_label)
        )
        if multi_label:
            binding["visual_grid_internal_labels"] = [
                label_key for label_key, _source in labels if label_key != key
            ]
        binding["product_context_nearby"] = True
        binding["product_context_distance"] = 0
        binding["visible_labels"] = [label_key for label_key, _source in labels]
        binding["visible_label_candidates"] = [
            {"label": label_key, "source": source_name}
            for label_key, source_name in labels
        ]
        binding["visual_grid_page_min"] = int(page_min)
        binding["visual_grid_page_max"] = int(page_max)
        binding["visual_grid_page_label_count"] = int(page_label_count)
        binding["visual_grid_sequence_confirmed"] = (
            binding_rule == "visual_grid_sequence_order"
        )
        binding["visual_grid_anchor_count"] = int(anchor_count)
        binding["visual_grid_sequence_position"] = int(idx + 1)
        binding["visual_grid_sequence_start"] = int(sequence_start)
        additions.append(binding)
    return additions


def _extract_visual_grid_label_bindings(
    processed_structures: List[Dict],
    active_cpds: List[str],
    visible_label_cache: Optional[Dict[str, Dict]],
) -> List[Dict]:
    """Bind dense structure-grid pages by the visible label printed under each drawing.

    This targets pages where the patent itself presents a regular grid of final
    product structures. In that layout prose context is sparse, but the visual
    label below the structure is the authoritative compound ID. The rule is
    intentionally page-level: it fires only when many structures and visible
    active labels form a coherent sequence on the same page.
    """
    if not active_cpds or not visible_label_cache:
        return []
    active_keys = _active_label_keys(active_cpds)
    by_page: Dict[int, List[Dict]] = {}
    for struct in processed_structures:
        by_page.setdefault(int(struct.get("page_no") or 0), []).append(struct)

    bindings: List[Dict] = []
    for page_no, page_structs in sorted(by_page.items()):
        shaped_structs = [
            struct
            for struct in page_structs
            if _is_contextual_final_visual_candidate(
                struct,
                {
                    "source": "page_wide",
                    "product_context_distance": 0,
                    "multi_label_crop": False,
                },
            )
        ]
        if len(shaped_structs) < 8:
            continue
        visible_items: List[Tuple[Dict, List[Tuple[str, str]]]] = []
        page_bases: List[int] = []
        for struct in shaped_structs:
            labels = _active_visible_keys_for_struct(
                struct, visible_label_cache, active_keys
            )
            if not labels:
                continue
            bases = [
                base
                for key, _source in labels
                for base in [_base_cpd_num(key)]
                if base is not None and base > 30
            ]
            if bases:
                visible_items.append((struct, labels))
                page_bases.extend(bases)
        if len(visible_items) < 6 or len(set(page_bases)) < 6:
            continue
        page_range = _dominant_visual_grid_base_range(page_bases, len(shaped_structs))
        if not page_range:
            continue
        page_min, page_max, page_label_count = page_range

        page_bindings = _visual_grid_sequence_order_bindings(
            page_structs,
            visible_items,
            active_keys,
            page_min,
            page_max,
            page_label_count,
        )
        if not page_bindings:
            page_bindings = []
            used_keys: set[str] = set()
            for struct, labels in sorted(
                visible_items,
                key=lambda item: (
                    float(item[0].get("y0") or 0),
                    float(item[0].get("x0") or 0),
                ),
            ):
                selected = _visual_grid_primary_key(labels, page_min, page_max)
                if not selected:
                    continue
                key, source, multi_label = selected
                if key in used_keys:
                    continue
                binding = _build_binding_from_structure(struct, key)
                binding["binding_rule"] = "visual_grid_label"
                binding["visible_label"] = key
                binding["visual_label_source"] = "visual_grid"
                binding["visible_label_crop_source"] = source
                binding["visible_label_multi_candidate"] = False
                if multi_label:
                    binding["visual_grid_internal_labels"] = [
                        label for label, _source in labels if label != key
                    ]
                binding["product_context_nearby"] = True
                binding["product_context_distance"] = 0
                binding["visible_labels"] = [label for label, _source in labels]
                binding["visible_label_candidates"] = [
                    {"label": label, "source": source_name}
                    for label, source_name in labels
                ]
                binding["visual_grid_page_min"] = int(page_min)
                binding["visual_grid_page_max"] = int(page_max)
                binding["visual_grid_page_label_count"] = int(page_label_count)
                page_bindings.append(binding)
                used_keys.add(key)
        if page_bindings:
            bindings.extend(page_bindings)

    if bindings:
        logger.info(
            "   👁 结构网格可见编号绑定: %d rows",
            len(bindings),
        )
    return _active_ordered_bindings(bindings, active_cpds)


def _extract_direct_label_bindings(
    doc,
    processed_structures: List[Dict],
    active_cpds: List[str],
    pages_text: Optional[Dict[int, str]] = None,
    word_cache: Optional[Dict[int, List[Dict]]] = None,
    focus_windows: Optional[Dict[int, List[Tuple[float, float]]]] = None,
    visible_label_cache: Optional[Dict[str, Dict]] = None,
    ocr_line_map: Optional[Dict[int, List[Any]]] = None,
) -> List[Dict]:
    """Bind structures whose own label matches an active compound number."""
    active_keys = _active_label_keys(active_cpds)
    active_bases = {_base_cpd_num(cpd) for cpd in active_cpds}
    active_bases.discard(None)
    if not active_keys:
        return []

    bindings: List[Dict] = []
    seen_pairs: set[tuple[int, str]] = set()
    focus_windows = focus_windows or {}
    lines_by_page = _normalise_ocr_line_map(ocr_line_map)
    for page_no in sorted(set(p["page_no"] for p in processed_structures)):
        if page_no < 1 or page_no > len(doc):
            continue
        page_structs = [p for p in processed_structures if p["page_no"] == page_no]
        page_text = _page_text_for_page_no(pages_text, page_no)
        page_lines = lines_by_page.get(page_no - 1) or []
        page_structs = _filter_items_by_focus_windows(
            page_structs, focus_windows.get(page_no), margin=70.0
        )
        rows_by_page = {
            page_no: _group_structures_by_row(page_structs, y_threshold=55.0)
        }
        for struct in page_structs:
            if (
                active_cpds
                and visible_label_cache
                and _is_structure_table_layout(
                    page_structs,
                    page_text,
                    ocr_lines=page_lines,
                    active_bases=active_bases,
                )
                and _is_probable_table_structure(struct, page_structs)
            ):
                # On structure-table pages the authoritative compound number is
                # the left ID column. Numeric OCR inside the drawing is often an
                # atom/NMR/route artifact and must not occupy the structure
                # before table-row binding runs.
                continue
            # Strongest evidence: the label is cropped with the structure
            # itself. Page-level OCR around structures is intentionally not
            # used here because nearby procedure text frequently contains
            # unrelated compound numbers and can steal bindings.
            cache_candidates = _visible_label_candidates_for_structure(
                struct, visible_label_cache
            )
            if cache_candidates:
                visual_candidates = _contextual_visible_label_candidates(
                    struct,
                    cache_candidates,
                    active_keys,
                    pages_text,
                    max_context_distance=1,
                    lines_by_page=lines_by_page,
                    row=_row_for_structure(struct, rows_by_page),
                )
            else:
                labels = [
                    label
                    for label in _visible_labels_for_structure(
                        doc,
                        struct,
                        visible_label_cache=visible_label_cache,
                        fast_only=True,
                    )
                    if _cpd_label_key(label) in active_keys
                ]
                visual_candidates = [
                    {
                        "label": _normalise_compound_label(str(label)),
                        "source": "ocr",
                        "product_context_distance": _product_context_distance(
                            pages_text, page_no, _base_cpd_num(label) or 0
                        )
                        if pages_text is not None
                        else 0,
                        "multi_label_crop": False,
                    }
                    for label in labels
                ]

            for visual_candidate in visual_candidates:
                label = _normalise_compound_label(
                    str(visual_candidate.get("label") or "")
                )
                label_key = _cpd_label_key(label)
                if label_key not in active_keys:
                    continue
                nearby_label_kind = _nearby_ocr_label_kind(
                    struct, label_key, lines_by_page
                )
                if nearby_label_kind == "racemic":
                    # Rac-Cpd-N is the pre-chiral-separation precursor. If the
                    # patent prints Cpd-N products too, activity-led binding
                    # must not let the same visible N steal the final structure.
                    continue
                ok_exact, exact_label = _passes_exact_visual_label_guard(
                    struct,
                    label_key,
                    lines_by_page,
                    row=_row_for_structure(struct, rows_by_page),
                )
                if not ok_exact:
                    continue
                has_product_context = True
                product_context_distance = int(
                    visual_candidate.get("product_context_distance") or 0
                )
                if pages_text is not None:
                    has_product_context = product_context_distance < 999
                    if not has_product_context:
                        continue
                if not _is_contextual_final_visual_candidate(struct, visual_candidate):
                    continue
                pair_key = (label_key, str(struct.get("id")))
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)
                binding = _build_binding_from_structure(struct, label_key)
                binding["binding_rule"] = "direct_structure_label"
                binding["visible_label"] = str(label)
                binding["visual_label_source"] = (
                    "cache"
                    if str(struct.get("id") or "") in (visible_label_cache or {})
                    else "ocr"
                )
                binding["visible_label_crop_source"] = str(
                    visual_candidate.get("source") or ""
                )
                binding["visible_label_multi_candidate"] = bool(
                    visual_candidate.get("multi_label_crop")
                )
                binding["product_context_nearby"] = has_product_context
                binding["product_context_distance"] = product_context_distance
                if nearby_label_kind:
                    binding["nearby_ocr_label_kind"] = nearby_label_kind
                if exact_label:
                    binding["nearby_exact_product_label"] = exact_label
                width = max(
                    0.0, float(struct.get("x1") or 0) - float(struct.get("x0") or 0)
                )
                height = max(
                    0.0, float(struct.get("y1") or 0) - float(struct.get("y0") or 0)
                )
                binding["struct_width"] = width
                binding["struct_height"] = height
                binding["struct_area"] = width * height
                bindings.append(binding)
    return bindings


def _extract_labeled_product_bindings(
    doc,
    processed_structures: List[Dict],
    pages_text: Optional[Dict[int, str]] = None,
    active_cpds: Optional[List[str]] = None,
    focus_windows: Optional[Dict[int, List[Tuple[float, float]]]] = None,
    ocr_line_map: Optional[Dict[int, List[Tuple[float, str]]]] = None,
    visible_label_cache: Optional[Dict[str, Dict]] = None,
) -> List[Dict]:
    """Bind structures by OCR labels immediately below/near the drawing.

    This is the primary fallback for scanned Chinese synthesis pages. It keeps
    only product-like numeric labels (1, 2, 4-2, 15-1) and ignores intermediate
    labels with letters (1a, 3b), preventing all reagent/intermediate drawings
    from leaking into final Step9 output.
    """
    bindings: List[Dict] = []
    used_structures: set[str] = set()
    used_labels: set[str] = set()
    word_cache: Dict[int, List[Dict]] = {}
    focus_windows = focus_windows or {}

    if pages_text:
        direct_label_bindings = _extract_direct_label_bindings(
            doc,
            processed_structures,
            active_cpds or [],
            pages_text=pages_text,
            word_cache=word_cache,
            focus_windows=focus_windows,
            visible_label_cache=visible_label_cache,
            ocr_line_map=ocr_line_map,
        )
        bindings.extend(direct_label_bindings)
        used_structures.update(b["structure_id"] for b in direct_label_bindings)
        used_labels.update(
            b["cpd"].replace("Compound ", "") for b in direct_label_bindings
        )

        pair_bindings = _extract_pair_heading_product_bindings(
            doc, pages_text, processed_structures, ocr_line_map=ocr_line_map
        )
        bindings.extend(pair_bindings)
        used_structures.update(b["structure_id"] for b in pair_bindings)
        used_labels.update(b["cpd"].replace("Compound ", "") for b in pair_bindings)

        letter_pair_bindings = _extract_cpd_letter_pair_product_bindings(
            pages_text,
            processed_structures,
            active_cpds=active_cpds or [],
            ocr_line_map=ocr_line_map,
        )
        bindings.extend(letter_pair_bindings)
        used_structures.update(b["structure_id"] for b in letter_pair_bindings)
        used_labels.update(
            b["cpd"].replace("Compound ", "") for b in letter_pair_bindings
        )

        table_bindings = _extract_structure_table_bindings(
            processed_structures,
            pages_text,
            active_cpds or [],
            [],
            ocr_line_map=ocr_line_map,
        )
        bindings.extend(table_bindings)
        used_structures.update(b["structure_id"] for b in table_bindings)
        used_labels.update(b["cpd"].replace("Compound ", "") for b in table_bindings)

        table_sequence_bindings = _extract_structure_table_sequence_bindings(
            processed_structures,
            pages_text,
            active_cpds or [],
            table_bindings,
            ocr_line_map=ocr_line_map,
        )
        bindings.extend(table_sequence_bindings)
        used_structures.update(b["structure_id"] for b in table_sequence_bindings)
        used_labels.update(
            b["cpd"].replace("Compound ", "") for b in table_sequence_bindings
        )

        paired_route_bindings = _extract_paired_route_product_bindings(
            processed_structures,
            pages_text,
            active_cpds or [],
            bindings,
        )
        bindings.extend(paired_route_bindings)
        used_structures.update(b["structure_id"] for b in paired_route_bindings)
        used_labels.update(
            b["cpd"].replace("Compound ", "") for b in paired_route_bindings
        )

        product_section_bindings = _extract_product_section_bindings(
            processed_structures,
            pages_text,
            active_cpds or [],
            bindings,
        )
        bindings.extend(product_section_bindings)
        used_structures.update(b["structure_id"] for b in product_section_bindings)
        used_labels.update(
            b["cpd"].replace("Compound ", "") for b in product_section_bindings
        )

    use_legacy_word_ocr_fallbacks = not active_cpds and not visible_label_cache
    if use_legacy_word_ocr_fallbacks:
        triplet_bindings = _extract_triplet_split_row_bindings(
            doc,
            processed_structures,
            used_structures,
            used_labels,
            word_cache=word_cache,
            focus_windows=focus_windows,
        )
        bindings.extend(triplet_bindings)

        dense_scheme_bindings = _extract_first_dense_scheme_product(
            processed_structures, bindings, used_structures, used_labels
        )
        bindings.extend(dense_scheme_bindings)

        bare_bindings = _extract_bare_product_label_bindings(
            doc,
            processed_structures,
            used_structures,
            used_labels,
            pages_text=pages_text,
            word_cache=word_cache,
            focus_windows=focus_windows,
        )
        bindings.extend(bare_bindings)

        split_reaction_bindings = _extract_split_reaction_bare_bindings(
            processed_structures, bindings, used_structures, used_labels
        )
        bindings.extend(split_reaction_bindings)
    else:
        logger.info("   跳过旧词级OCR fallback：活性表+可见标签缓存已接管结构绑定")

    pages = sorted({p["page_no"] for p in processed_structures})
    if active_cpds and visible_label_cache:
        bindings.sort(key=_binding_sort_key)
        return bindings

    for page_no in pages:
        if page_no < 1 or page_no > len(doc):
            continue
        page_structs = sorted(
            [p for p in processed_structures if p["page_no"] == page_no],
            key=lambda p: (p["y0"], p["x0"]),
        )
        page_windows = focus_windows.get(page_no)
        page_structs = _filter_items_by_focus_windows(
            page_structs, page_windows, margin=60.0
        )
        if not page_structs:
            continue
        words = _get_ocr_word_coords(doc[page_no - 1], cache=word_cache)
        words = _filter_items_by_focus_windows(words, page_windows, margin=80.0)
        if not words:
            continue

        for struct in page_structs:
            if struct["id"] in used_structures:
                continue
            x0, x1 = float(struct["x0"]), float(struct.get("x1", struct["x0"]))
            y0, y1 = float(struct["y0"]), float(struct.get("y1", struct["y0"]))
            cx = (x0 + x1) / 2
            width = max(25.0, x1 - x0)

            candidates = []
            for word in words:
                label = _normalise_compound_label(word["text"])
                if not _FINAL_COMPOUND_LABEL_RE.fullmatch(label):
                    continue
                dx = abs(float(word["x"]) - cx)
                y = float(word["y"])
                below = y1 - 5 <= y <= y1 + 55
                inside_or_above_bottom = y0 <= y <= y1 + 20
                if dx <= max(width * 0.55, 35.0) and (below or inside_or_above_bottom):
                    dy = abs(y - y1) if below else abs(y - y0)
                    candidates.append((dy + dx * 0.05, label, word))

            if not candidates:
                continue
            _, label, _word = min(candidates, key=lambda x: x[0])
            if label in used_labels:
                continue
            used_labels.add(label)
            used_structures.add(struct["id"])
            binding = _build_binding_from_structure(struct, label)
            binding["binding_rule"] = "ocr_numeric_structure_label"
            bindings.append(binding)

    bindings.sort(key=_binding_sort_key)
    split_bases = [
        int(m.group(1))
        for b in bindings
        for m in [re.match(r"^Compound\s+(\d+)-[12]$", b["cpd"])]
        if m
    ]
    if split_bases:
        max_split_base = max(split_bases)
        before = len(bindings)
        bindings = [
            b
            for b in bindings
            if not (
                re.match(r"^Compound\s+\d+$", b["cpd"])
                and int(b["cpd"].split()[-1]) > max_split_base + 2
                and b.get("binding_rule")
                in {
                    "ocr_numeric_structure_label",
                    "ocr_bare_numeric_product_label",
                }
            )
        ]
        removed = before - len(bindings)
        if removed:
            logger.info(f"   OCR标签后过滤: 去除 {removed} 个疑似粘连数字标签")
    return bindings
