"""Single candidate construction, ordering and conflict ranking."""

from __future__ import annotations

import os
import re
from pathlib import (
    Path,
)
from typing import (
    Any,
    Dict,
    List,
    Optional,
    Tuple,
)

from .binding_geometry import (
    _attach_structure_geometry,
    _has_strong_structure_table_row_evidence,
    _is_complete_product_like_structure,
    _is_final_label_band_product_like,
)
from .binding_labels import (
    _STRICT_VISIBLE_LABEL_SOURCES,
    _VISIBLE_LABEL_SOURCE_RANK,
    _active_label_keys,
    _base_cpd_num,
    _binding_base_num,
    _binding_label_key,
    _cpd_label_key,
    _int_or_default,
    _is_short_internal_visible_key,
    _is_truncated_visible_prefix,
    _nearby_exact_product_label,
    _normalise_compound_label,
    _product_context_distance,
    _strict_visible_label_keys_for_binding,
    _visible_label_keys_for_binding,
    _visual_label_keys_for_binding,
)


def _build_binding_from_structure(struct: Dict, label: str) -> Dict:
    label_key = _normalise_compound_label(str(label))
    cpd = f"Compound {label_key}"
    label_num = _base_cpd_num(label_key) or 0
    binding = {
        "cpd": cpd,
        "example_id": cpd,
        "example_num": label_num,
        "compound_id": cpd,
        "compound_num": label_num,
        "cpd_num": label_num,
        "prefix": "Compound",
        "structure_id": struct["id"],
        "page_no": struct["page_no"],
        "structure_index": struct["idx"],
        "struct_x0": struct["x0"],
        "struct_y0": struct["y0"],
        "image_path": struct["image_path"],
        "source_image_path": struct["image_path"],
        "ocsr_image_path": struct["image_path"],
        "candidates": 1,
        "binding_rule": "ocr_pair_heading_structure_order",
    }
    return _attach_structure_geometry(binding, struct)


def _normalise_binding_to_compound(binding: Dict, compound_label) -> Dict:
    raw_label = str(compound_label or "").strip()
    label_key = (
        "CLAIM1"
        if raw_label.upper() == "CLAIM1"
        else (_cpd_label_key(compound_label) or raw_label)
    )
    if label_key == "CLAIM1":
        cpd = "Claim 1 compound"
        binding["cpd"] = cpd
        binding["cpd_id"] = cpd
        binding["example_id"] = cpd
        binding["example_num"] = 1
        binding["compound_id"] = cpd
        binding["compound_num"] = 1
        binding["cpd_num"] = 1
        binding["prefix"] = "Claim"
        return binding
    cpd = f"Compound {label_key}"
    compound_num = _base_cpd_num(label_key) or 0
    binding["cpd"] = cpd
    binding["example_id"] = cpd
    binding["example_num"] = compound_num
    binding["compound_id"] = cpd
    binding["compound_num"] = compound_num
    binding["cpd_num"] = compound_num
    binding["prefix"] = "Compound"
    return binding


def _binding_sort_key(binding: Dict) -> Tuple[int, int, int, float, float]:
    m = re.match(
        r"^Compound\s+([1-9]\d*)(?:-([12]))?([A-Z])?$",
        str(binding.get("cpd", "")),
        re.IGNORECASE,
    )
    if m:
        suffix_rank = int(m.group(2) or 0)
        letter_rank = ord(m.group(3).upper()) - 64 if m.group(3) else 0
        return (
            int(m.group(1)),
            suffix_rank * 100 + letter_rank,
            int(binding.get("page_no") or 0),
            float(binding.get("struct_y0") or 0),
            float(binding.get("struct_x0") or 0),
        )
    return (
        10**9,
        10**9,
        int(binding.get("page_no") or 0),
        float(binding.get("struct_y0") or 0),
        float(binding.get("struct_x0") or 0),
    )


def _has_exact_visual_product_evidence(
    binding: Dict, active_keys: Optional[set[str]] = None
) -> bool:
    key = _binding_label_key(binding)
    if not key:
        return False
    visual_keys = _visual_label_keys_for_binding(binding)
    if key not in visual_keys:
        return False
    competing = visual_keys - {key}
    if active_keys:
        competing = {item for item in competing if item in active_keys}
    if competing:
        return False
    if bool(
        binding.get("visible_label_multi_candidate")
    ) and key not in _strict_visible_label_keys_for_binding(binding):
        return False
    distance = _int_or_default(binding.get("product_context_distance"), 999)
    if binding.get("product_context_nearby") is True and distance <= 1:
        return True
    nearby_exact = _cpd_label_key(str(binding.get("nearby_exact_product_label") or ""))
    return nearby_exact == key


def _visible_label_conflict_rank(
    binding: Dict, active_keys: Optional[set[str]] = None
) -> int:
    """Penalize candidates whose own visual label proves another active ID."""
    key = _binding_label_key(binding)
    strict_keys = _strict_visible_label_keys_for_binding(binding)
    visible_keys = strict_keys or _visible_label_keys_for_binding(binding)
    if not key or not visible_keys:
        return 1
    if str(binding.get("binding_rule") or "") == "visual_grid_label":
        all_visible_keys = _visible_label_keys_for_binding(binding)
        base = _base_cpd_num(key)
        try:
            page_min = int(binding.get("visual_grid_page_min") or 0)
            page_max = int(binding.get("visual_grid_page_max") or 0)
        except Exception:
            page_min = page_max = 0
        if (
            key in all_visible_keys
            and base is not None
            and page_min <= base <= page_max
        ):
            competing_in_grid = {
                vkey
                for vkey in all_visible_keys
                if vkey != key
                and (vbase := _base_cpd_num(vkey)) is not None
                and page_min <= vbase <= page_max
            }
            if not competing_in_grid:
                return 0
    if key in visible_keys:
        return 0
    if str(binding.get("binding_rule") or "") in {
        "structure_table_row_order",
        "structure_table_row_order_inferred",
        "structure_table_row_order_corrected",
    } and all(_is_short_internal_visible_key(key, vkey or "") for vkey in visible_keys):
        return 1
    if (
        str(binding.get("binding_rule") or "")
        in {
            "structure_table_row_order",
            "structure_table_row_order_inferred",
            "structure_table_row_order_corrected",
        }
        and re.fullmatch(r"\d{3}[A-Z]?", key)
        and all(re.fullmatch(r"\d{1,2}[A-Z]?", vkey or "") for vkey in visible_keys)
    ):
        # Table-row bindings are often correct even when OCR sees small atom,
        # reagent, or route annotations inside the drawing. Do not let "1" or
        # "11" override a three-digit left-column row number without an exact
        # competing visual label for that target.
        return 1
    if visible_keys and all(
        _is_truncated_visible_prefix(key, vkey) for vkey in visible_keys
    ):
        # PaddleX sometimes clips the final digit from a tight label crop
        # (Example 134 -> "13"). Treat that as weak evidence unless another
        # exact candidate exists for the shorter active number.
        return 1
    if _has_strong_structure_table_row_evidence(binding):
        # In a structure table the row ID is outside the molecule crop. A small
        # strict digit inside the drawing is usually an atom, stereochemistry,
        # or procedure annotation, not a competing final compound ID.
        return 1
    if key in strict_keys and key != "1" and (strict_keys - {key}) <= {"1"}:
        # Stereochemical annotations such as "or1" are often OCR'd as an
        # additional strict "1" inside the same crop. If the target label is
        # also present, do not turn that annotation into an active-label conflict.
        return 0
    if key in strict_keys and all(
        vkey == key or _is_short_internal_visible_key(key, vkey or "")
        for vkey in strict_keys
    ):
        return 0
    if key in strict_keys and strict_keys - {key}:
        return 5
    if strict_keys and active_keys and any(vkey in active_keys for vkey in strict_keys):
        return 5
    if active_keys and any(vkey in active_keys for vkey in visible_keys):
        return 3
    return 2


def _is_low_internal_label_in_multi_visible_crop(binding: Dict) -> bool:
    """Detect low route/intermediate numbers inside a crop labelled as a later product."""
    if str(binding.get("binding_rule") or "") == "visual_grid_label":
        return False
    key = _binding_label_key(binding)
    base = _base_cpd_num(key)
    if base is None or base > 20:
        return False
    visible_bases = [
        n
        for n in (
            _base_cpd_num(label) for label in _visible_label_keys_for_binding(binding)
        )
        if n is not None
    ]
    if len(set(visible_bases)) < 2:
        return False
    return max(visible_bases) >= max(50, base + 30)


def _visible_label_exactness_rank(
    binding: Dict, active_keys: Optional[set[str]] = None
) -> int:
    key = _binding_label_key(binding)
    strict_keys = _strict_visible_label_keys_for_binding(binding)
    visible_keys = _visible_label_keys_for_binding(binding)
    if (
        key
        and key in strict_keys
        and not _is_low_internal_label_in_multi_visible_crop(binding)
    ):
        return 0
    if key and key in strict_keys:
        return 3
    if (
        key
        and key in visible_keys
        and not _is_low_internal_label_in_multi_visible_crop(binding)
    ):
        return 1
    if (
        visible_keys
        and active_keys
        and any(vkey in active_keys for vkey in visible_keys)
    ):
        return 4
    return 2


def _strict_visible_source_rank(binding: Dict) -> int:
    """Return best strict visual-label source rank for the binding target."""
    key = _binding_label_key(binding)
    if not key:
        return 99
    best = 99
    for candidate in binding.get("visible_label_candidates") or []:
        source = str(candidate.get("source") or "")
        if source not in _STRICT_VISIBLE_LABEL_SOURCES:
            continue
        if _cpd_label_key(str(candidate.get("label") or "")) != key:
            continue
        best = min(best, _VISIBLE_LABEL_SOURCE_RANK.get(source, 99))
    if (
        best == 99
        and binding.get("visible_label_crop_source") in _STRICT_VISIBLE_LABEL_SOURCES
    ):
        if _cpd_label_key(str(binding.get("visible_label") or "")) == key:
            best = min(
                best,
                _VISIBLE_LABEL_SOURCE_RANK.get(
                    str(binding.get("visible_label_crop_source") or ""), 99
                ),
            )
    return best


def _binding_priority(
    binding: Dict, active_keys: Optional[set[str]] = None
) -> Tuple[int, int, int, int]:
    """Prefer explicit OCR/table labels over broad heading-window fallbacks."""
    rule = str(binding.get("binding_rule") or "")
    key = _binding_label_key(binding)
    active_rank = 0 if active_keys and key in active_keys else 1
    rule_rank = {
        "authoritative_structure_table_sequence": -1,
        "direct_structure_label": 1,
        "direct_structure_label_right_product_crop": 1,
        "visual_grid_label": 0,
        "product_section_context": 1,
        "structure_table_row_order": 0,
        "structure_table_row_order_corrected": 0,
        "structure_table_row_order_inferred": 0,
        "ocr_pair_heading_structure_order": 3,
        "paired_route_product_row_order": 4,
        "triplet_split_row_structure_order": 5,
        "split_reaction_product_label": 6,
        "ocr_numeric_structure_label": 7,
        "ocr_bare_numeric_product_label": 8,
        "heading_row_right_product_recovery": 2,
        "same_row_right_product_repair": 2,
        "route_title_row_right_product": 2,
    }
    rank = rule_rank.get(rule, 20 if rule else 30)
    return (
        active_rank,
        rank,
        int(binding.get("candidates") or 9999),
        int(binding.get("structure_index") or 999999),
    )


def _direct_visual_shape_rank(binding: Dict) -> int:
    """Rank visually-labeled crops by whether they look like final products."""
    area = float(binding.get("struct_area") or 0)
    width = float(binding.get("struct_width") or 0)
    height = float(binding.get("struct_height") or 0)
    if area and area < 5000:
        return 5
    if width and height and width / max(height, 1.0) > 5.5:
        return 4
    if area >= 18000 and width >= 250 and height >= 85:
        return 0
    return 1


def _is_weak_direct_visual_binding(binding: Optional[Dict]) -> bool:
    """Return True when direct OCR evidence should be rechecked visually.

    A visible numeric label is strong evidence only when the crop is plausibly a
    final product module. Tiny fragments, whole reaction routes, and labels far
    from the product heading must not lock the binding before module repair.
    """
    if not binding:
        return False
    if str(binding.get("binding_rule") or "") != "direct_structure_label":
        return False
    shape_rank = _direct_visual_shape_rank(binding)
    if shape_rank >= 4:
        return True
    key = _binding_label_key(binding)
    if (
        re.fullmatch(r"[1-9]", key or "")
        and float(binding.get("struct_area") or 0) < 6400
        and float(binding.get("struct_height") or 0) < 95
    ):
        # Route step numbers are overwhelmingly single-digit. If one still
        # lands on a compact crop, force the later strict-label repair pass to
        # compare it against complete Cpd-labelled product modules.
        return True
    if str(binding.get("visual_label_source") or "") not in {
        "module",
        "route_right_product",
    }:
        return True
    distance = binding.get("product_context_distance")
    if distance is not None:
        try:
            if int(distance) > 1:
                return True
        except Exception:
            pass
    return False


def _visual_binding_priority(
    binding: Dict, active_keys: Optional[set[str]] = None
) -> Tuple[int, ...]:
    """Tie-break visual label candidates without favoring route fragments.

    The same compound number can appear both under a standalone final-product
    drawing and inside a reaction scheme. Prefer candidates with product
    context, then larger standalone-looking crops, while still keeping visual
    labels ahead of prose-derived fallbacks.
    """
    base_priority = _binding_priority(binding, active_keys)
    rule = str(binding.get("binding_rule") or "")
    context_distance = binding.get("product_context_distance")
    if context_distance is None:
        context_distance = 0 if binding.get("product_context_nearby") is True else 999
    try:
        context_rank = int(context_distance)
    except Exception:
        context_rank = 999
    area = float(binding.get("struct_area") or 0)
    shape_rank = _direct_visual_shape_rank(binding)
    source = str(binding.get("visual_label_source") or "")
    if (
        rule
        in {
            "authoritative_structure_table_sequence",
            "structure_table_row_order",
            "structure_table_row_order_inferred",
            "structure_table_row_order_corrected",
        }
        and area >= 6500
    ):
        shape_rank = 0
    source_rank = {
        "module": 0,
        "cache_fill": 0,
        "cache_confirmed": 0,
        "route_right_product": 1,
    }.get(source, 2)
    if rule in {"direct_structure_label", "direct_structure_label_right_product_crop"}:
        try:
            row_rank = int(float(binding.get("struct_y0") or 999999))
        except Exception:
            row_rank = 999999
        try:
            column_rank = int(float(binding.get("struct_x0") or 999999))
        except Exception:
            column_rank = 999999
    else:
        row_rank = 999999
        column_rank = 999999
    # Negative values sort larger standalone crops first.
    return (
        base_priority[0],
        _visible_label_conflict_rank(binding, active_keys),
        _strict_visible_source_rank(binding),
        base_priority[1],
        context_rank
        if rule
        in {"direct_structure_label", "direct_structure_label_right_product_crop"}
        else 999,
        source_rank,
        shape_rank,
        base_priority[2],
        row_rank,
        column_rank,
        -int(area),
        base_priority[3],
    )


def _merge_binding_candidates(
    primary: List[Dict], fallback: List[Dict], active_cpds: Optional[List[str]] = None
) -> List[Dict]:
    """Merge binding candidates, keeping one best structure per exact compound label."""
    active_keys = _active_label_keys(active_cpds)
    all_candidates = [*primary, *fallback]
    table_structures: set[str] = set()
    for binding in all_candidates:
        rule = str(binding.get("binding_rule") or "")
        struct_id = str(binding.get("structure_id") or "")
        if struct_id and rule == "authoritative_structure_table_sequence":
            table_structures.add(struct_id)
            continue
        if (
            struct_id
            and rule
            in {
                "authoritative_structure_table_sequence",
                "structure_table_row_order",
                "structure_table_row_order_inferred",
                "structure_table_row_order_corrected",
            }
            and float(binding.get("struct_area") or 0) >= 6500
        ):
            table_structures.add(struct_id)

    by_key: Dict[str, Dict] = {}
    used_structures: set[str] = set()

    def _merge_priority(
        binding: Dict,
    ) -> Tuple[int, int, int, int, int, int, int, int, int]:
        rule = str(binding.get("binding_rule") or "")
        struct_id = str(binding.get("structure_id") or "")
        table_guard = (
            0
            if (
                rule
                in {
                    "authoritative_structure_table_sequence",
                    "structure_table_row_order",
                    "structure_table_row_order_inferred",
                    "structure_table_row_order_corrected",
                }
                and struct_id in table_structures
            )
            else 1
        )
        internal_label_penalty = (
            1
            if (
                rule == "direct_structure_label"
                and struct_id in table_structures
                and len(_visible_label_keys_for_binding(binding)) <= 1
            )
            else 0
        )
        return (
            table_guard,
            internal_label_penalty,
            *_visual_binding_priority(binding, active_keys),
        )

    for binding in sorted(all_candidates, key=_merge_priority):
        key = _binding_label_key(binding)
        struct_id = str(binding.get("structure_id") or "")
        if not key or not struct_id:
            continue
        if key in by_key or struct_id in used_structures:
            continue
        by_key[key] = binding
        used_structures.add(struct_id)
    return sorted(by_key.values(), key=_binding_sort_key)


def _is_contextual_final_visual_candidate(
    struct: Dict, visual_candidate: Dict[str, Any]
) -> bool:
    """Accept visually labelled structures only when they are not route fragments.

    Some synthesis schemes contain labels like ``6.1``; OCR can split those into
    active-looking labels (``6`` and ``1``).  A small or multi-label crop must not
    become a final product unless it has very tight product context.
    """
    if _is_complete_product_like_structure(struct):
        return True
    source = str(visual_candidate.get("source") or "")
    if source == "page_wide" and not bool(visual_candidate.get("multi_label_crop")):
        width = max(0.0, float(struct.get("x1") or 0) - float(struct.get("x0") or 0))
        height = max(0.0, float(struct.get("y1") or 0) - float(struct.get("y0") or 0))
        area = width * height
        aspect = width / max(height, 1.0)
        if area >= 5000 and width >= 90 and height >= 48 and aspect <= 3.2:
            return True
    if _is_final_label_band_product_like(struct, visual_candidate):
        return True

    try:
        distance = _int_or_default(
            visual_candidate.get("product_context_distance"), 999
        )
    except Exception:
        distance = 999
    if distance != 0 or bool(visual_candidate.get("multi_label_crop")):
        return False

    width = max(0.0, float(struct.get("x1") or 0) - float(struct.get("x0") or 0))
    height = max(0.0, float(struct.get("y1") or 0) - float(struct.get("y0") or 0))
    area = width * height
    aspect = width / max(height, 1.0)
    return area >= 4500 and width >= 65 and height >= 45 and aspect <= 4.8


def _strict_single_visible_candidate_for_missing(
    struct: Dict,
    candidates: List[Dict[str, str]],
    missing_keys: set[str],
    active_keys: set[str],
    pages_text: Optional[Dict[int, str]] = None,
    lines_by_page: Optional[Dict[int, List[Tuple[float, str]]]] = None,
    row: Optional[List[Dict]] = None,
) -> Optional[Dict[str, Any]]:
    """Allow activity-only backfill from visual OCR when the crop is unambiguous.

    This is deliberately narrower than normal direct-label binding. It fires only
    for missing active compounds, only when a strict crop sees one active label,
    and only when the structure looks like a complete product rather than a
    reagent/intermediate fragment or reaction arrow.
    """
    strict_matches: List[Dict[str, Any]] = []
    active_labels_seen: set[str] = set()
    for candidate in candidates:
        source = str(candidate.get("source") or "")
        label = _normalise_compound_label(str(candidate.get("label") or ""))
        key = _cpd_label_key(label)
        if not key:
            continue
        if key in active_keys:
            active_labels_seen.add(key)
        if source not in _STRICT_VISIBLE_LABEL_SOURCES or key not in missing_keys:
            continue
        strict_matches.append({"label": label, "label_key": key, "source": source})

    match_keys = {str(item.get("label_key") or "") for item in strict_matches}
    if len(match_keys) != 1:
        return None
    key = next(iter(match_keys))
    if active_labels_seen - {key}:
        return None
    best_source = sorted(
        strict_matches,
        key=lambda item: _VISIBLE_LABEL_SOURCE_RANK.get(
            str(item.get("source") or ""), 99
        ),
    )[0]
    if not (
        _is_complete_product_like_structure(struct)
        or _is_final_label_band_product_like(struct, best_source)
    ):
        return None

    exact_label = _nearby_exact_product_label(struct, key, lines_by_page, row=row)
    if exact_label and exact_label != key:
        return None
    product_context_distance = 999
    if pages_text is not None:
        product_context_distance = _product_context_distance(
            pages_text,
            int(struct.get("page_no") or 0),
            _base_cpd_num(key) or 0,
        )
    strict_matches.sort(
        key=lambda item: _VISIBLE_LABEL_SOURCE_RANK.get(
            str(item.get("source") or ""), 99
        )
    )
    best = strict_matches[0]

    # A strict/direct/PDF visual label on a complete product-like structure is
    # authoritative. Nearby text context is helpful but not required; otherwise
    # patents with dense structure grids and sparse prose bind only a handful of
    # compounds despite clear visual labels.
    source_rank = _VISIBLE_LABEL_SOURCE_RANK.get(str(best.get("source") or ""), 99)
    if (
        source_rank > _VISIBLE_LABEL_SOURCE_RANK.get("pdf_clip", 3)
        and exact_label != key
        and product_context_distance > 1
    ):
        return None

    return {
        "label": str(best.get("label") or key),
        "label_key": key,
        "source": str(best.get("source") or ""),
        "product_context_distance": product_context_distance,
        "multi_label_crop": False,
        "strict_visual_missing_backfill": True,
    }


def _active_ordered_bindings(
    final_bindings: List[Dict], active_cpds: List[str]
) -> List[Dict]:
    """Use activity compounds as the canonical output set and order.

    Binder candidates are still useful for finding images, but downstream final
    tables must not be driven by non-active synthesis/intermediate headings.
    """
    if not active_cpds:
        return sorted(final_bindings, key=_binding_sort_key)

    by_key: Dict[str, Dict] = {}
    active_keys = _active_label_keys(active_cpds)
    for binding in sorted(
        final_bindings, key=lambda b: _visual_binding_priority(b, active_keys)
    ):
        key = _binding_label_key(binding)
        if not key or key not in active_keys or key in by_key:
            continue
        by_key[key] = _normalise_binding_to_compound(dict(binding), key)

    ordered: List[Dict] = []
    for cpd in active_cpds:
        key = _cpd_label_key(cpd)
        if key in by_key:
            ordered.append(by_key[key])
    return ordered


def _final_structure_binding_quality(
    binding: Dict, active_keys: Optional[set[str]] = None
) -> Tuple[int, int, int, int, int, int, int]:
    """Final arbitration score: one active compound per actual structure crop."""
    rule = str(binding.get("binding_rule") or "")
    area = float(binding.get("struct_area") or 0)
    width = float(binding.get("struct_width") or 0)
    height = float(binding.get("struct_height") or 0)
    aspect = width / max(height, 1.0) if width and height else 999.0
    weak_shape = (
        1 if (area < 6000 or (width > 0 and height > 0 and aspect > 5.5)) else 0
    )
    if (
        rule
        in {
            "structure_table_row_order",
            "structure_table_row_order_inferred",
            "structure_table_row_order_corrected",
        }
        and area >= 6500
    ):
        weak_shape = 0
    fallback_rank = (
        1
        if rule
        in {
            "heading_range_fallback",
            "product_section_context",
            "paired_route_product_row_order",
            "triplet_split_row_structure_order",
            "split_reaction_product_label",
            "ocr_numeric_structure_label",
            "ocr_bare_numeric_product_label",
            "dense_scheme_final_product",
            "heading_row_right_product_recovery",
            "same_row_right_product_repair",
            "route_title_row_right_product",
        }
        else 0
    )
    direct_rank = (
        0
        if rule
        in {"direct_structure_label", "direct_structure_label_right_product_crop"}
        else 1
    )
    context_distance = binding.get("product_context_distance")
    try:
        context_rank = int(context_distance)
    except Exception:
        context_rank = 999
    return (
        fallback_rank,
        weak_shape,
        _visible_label_exactness_rank(binding, active_keys),
        _visible_label_conflict_rank(binding, active_keys),
        direct_rank,
        context_rank,
        -int(area),
    )


def _derive_right_product_binding(binding: Dict, output_dir: str) -> Optional[Dict]:
    """For a wide reaction-route crop, derive a right-end product crop.

    Some pages are segmented as a whole reaction route with the final label
    printed under the right-end product. OCSR should see the product module, not
    the full route. This deterministic crop is only used for unusually wide
    direct-label bindings.
    """
    image_path = str(binding.get("image_path") or "")
    if not image_path or not os.path.exists(image_path):
        return None
    width = float(binding.get("struct_width") or 0)
    height = float(binding.get("struct_height") or 0)
    aspect = width / max(height, 1.0) if width and height else 0.0
    if width <= 0 or height <= 0 or aspect <= 5.5:
        return None
    if width * height < 6500:
        return None
    labels = _visible_label_keys_for_binding(binding)
    target_key = _binding_label_key(binding)
    if labels - {target_key}:
        return None
    if str(binding.get("binding_rule") or "") == "direct_structure_label" and str(
        binding.get("visual_label_source") or ""
    ) in {"module", "clean_standalone_arbitration", "cache_confirmed"}:
        return None
    try:
        from PIL import Image
    except Exception:
        return None
    try:
        img = Image.open(image_path).convert("RGB")
    except Exception:
        return None

    crop_left = int(img.width * 0.58)
    crop = img.crop((crop_left, 0, img.width, img.height))
    derived_width = float(binding.get("struct_width") or 0) * 0.42
    derived_height = float(binding.get("struct_height") or 0)
    derived_area = derived_width * derived_height
    derived_aspect = (
        derived_width / max(derived_height, 1.0)
        if derived_width and derived_height
        else 0.0
    )
    if derived_area < 6500 or derived_aspect > 5.0:
        return None
    derived_dir = Path(output_dir) / "derived_structures"
    derived_dir.mkdir(parents=True, exist_ok=True)
    base = _binding_base_num(binding) or binding.get("compound_num") or "unknown"
    src_id = str(binding.get("structure_id") or "structure")
    derived_path = derived_dir / f"{src_id}_compound_{base}_right_product.png"
    crop.save(derived_path)

    derived = dict(binding)
    derived["source_structure_id"] = binding.get("structure_id")
    derived["structure_id"] = f"{src_id}_right_product"
    derived["image_path"] = str(binding.get("image_path") or "")
    derived["display_image_path"] = str(binding.get("image_path") or "")
    derived["source_image_path"] = str(binding.get("image_path") or "")
    derived["ocsr_image_path"] = str(derived_path)
    derived["binding_rule"] = "direct_structure_label_right_product_crop"
    derived["visual_label_source"] = "route_right_product"
    derived["struct_width"] = derived_width
    derived["struct_area"] = derived_area
    derived["struct_aspect"] = derived_aspect
    return derived
