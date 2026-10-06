"""Single candidate construction, ordering and conflict ranking."""

from __future__ import annotations

import re

from .binding_geometry import (
    _attach_structure_geometry,
    _has_strong_structure_table_row_evidence,
)
from .binding_labels import (
    _STRICT_VISIBLE_LABEL_SOURCES,
    _VISIBLE_LABEL_SOURCE_RANK,
    _active_label_keys,
    _base_cpd_num,
    _binding_label_key,
    _cpd_label_key,
    _is_short_internal_visible_key,
    _is_truncated_visible_prefix,
    _normalise_compound_label,
    _strict_visible_label_keys_for_binding,
    _visible_label_keys_for_binding,
)


def _build_binding_from_structure(struct: dict, label: str) -> dict:
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


def _normalise_binding_to_compound(binding: dict, compound_label) -> dict:
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


def _binding_sort_key(binding: dict) -> tuple[int, int, int, float, float]:
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


def _visible_label_conflict_rank(
    binding: dict, active_keys: set[str] | None = None
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
        except (TypeError, ValueError, OverflowError):
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


def _is_low_internal_label_in_multi_visible_crop(binding: dict) -> bool:
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


def _strict_visible_source_rank(binding: dict) -> int:
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
        and _cpd_label_key(str(binding.get("visible_label") or "")) == key
    ):
        best = min(
            best,
            _VISIBLE_LABEL_SOURCE_RANK.get(
                str(binding.get("visible_label_crop_source") or ""), 99
            ),
        )
    return best


def _binding_priority(
    binding: dict, active_keys: set[str] | None = None
) -> tuple[int, int, int, int]:
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


def _direct_visual_shape_rank(binding: dict) -> int:
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


def _visual_binding_priority(
    binding: dict, active_keys: set[str] | None = None
) -> tuple[int, ...]:
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
    except (TypeError, ValueError, OverflowError):
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
        except (TypeError, ValueError, OverflowError):
            row_rank = 999999
        try:
            column_rank = int(float(binding.get("struct_x0") or 999999))
        except (TypeError, ValueError, OverflowError):
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
    primary: list[dict], fallback: list[dict], active_cpds: list[str] | None = None
) -> list[dict]:
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

    by_key: dict[str, dict] = {}
    used_structures: set[str] = set()

    def _merge_priority(
        binding: dict,
    ) -> tuple[int, int, int, int, int, int, int, int, int]:
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


def _active_ordered_bindings(
    final_bindings: list[dict], active_cpds: list[str]
) -> list[dict]:
    """Use activity compounds as the canonical output set and order.

    Binder candidates are still useful for finding images, but downstream final
    tables must not be driven by non-active synthesis/intermediate headings.
    """
    if not active_cpds:
        return sorted(final_bindings, key=_binding_sort_key)

    by_key: dict[str, dict] = {}
    active_keys = _active_label_keys(active_cpds)
    for binding in sorted(
        final_bindings, key=lambda b: _visual_binding_priority(b, active_keys)
    ):
        key = _binding_label_key(binding)
        if not key or key not in active_keys or key in by_key:
            continue
        by_key[key] = _normalise_binding_to_compound(dict(binding), key)

    ordered: list[dict] = []
    for cpd in active_cpds:
        key = _cpd_label_key(cpd)
        if key in by_key:
            ordered.append(by_key[key])
    return ordered
