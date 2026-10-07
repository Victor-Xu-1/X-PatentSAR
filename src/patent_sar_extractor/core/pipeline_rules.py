"""Global accuracy-first rules for PatentSAR Extractor.

These rules are intentionally patent-agnostic.  The pipeline should only mark
rows as "confirmed" when the binding is backed by strong visual/table evidence;
otherwise it must fail closed and ask for review instead of silently pretending
the result is certain.
"""

from __future__ import annotations

from typing import Any

from patent_sar_extractor.contracts import ruleset_ref
from patent_sar_extractor.core.numbered_structure_binding import (
    valid_cell_binding_evidence,
)

from .activity_identity import printed_identifier_key
from .heading_evidence import valid_heading_binding_evidence

STRICT_VISIBLE_SOURCES = {"page_strict", "direct", "pdf_clip"}
VISUAL_LABEL_SOURCES = STRICT_VISIBLE_SOURCES | {"page_wide"}

STRONG_BINDING_RULES = {
    "original_heading_standalone",
    "numbered_structure_table_cell",
    "direct_structure_label",
    "direct_structure_label_merged_fragment",
    "direct_structure_label_right_product_crop",
    "visual_grid_label",
    "visual_grid_sequence_order",
    "authoritative_structure_table_sequence",
    "structure_table_row_order",
    "structure_table_row_order_inferred",
    "structure_table_row_order_corrected",
    "cmpd_overview_table_order",
    "singleton_claim_formula_structure",
    "heading_range_fallback",
    "route_title_row_right_product",
    "ocr_pair_heading_structure_order",
    "cpd_letter_pair_row_order",
}

REVIEW_BINDING_RULES = {
    "heading_range_fallback",
    "product_section_context",
    "route_title_row_right_product",
    "heading_row_right_product_recovery",
    "paired_route_product_row_order",
    "triplet_split_row_structure_order",
    "split_reaction_product_label",
    "dense_scheme_final_product",
    "ocr_numeric_structure_label",
    "ocr_bare_numeric_product_label",
    "scanned_pdf_structure_sequence_fallback",
}


def _label_key(value: Any) -> str:
    return printed_identifier_key(value)


def _int_or_default(value: Any, default: int = 999) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (ValueError, TypeError, OverflowError):
        return default


def _is_short_internal_annotation(target_key: str, conflict_key: str) -> bool:
    import re

    if not target_key or not conflict_key or target_key == conflict_key:
        return False
    if not re.fullmatch(r"\d{2,3}[A-Z]?", target_key):
        return False
    if not re.fullmatch(r"\d{1,2}[A-Z]?", conflict_key):
        return False
    target_num = re.match(r"\d+", target_key)
    conflict_num = re.match(r"\d+", conflict_key)
    if not target_num or not conflict_num:
        return False
    target_value = int(target_num.group(0))
    conflict_value = int(conflict_num.group(0))
    if conflict_value <= 20 and conflict_key == "1":
        return True
    # Strict OCR crops frequently include atom/procedure annotations printed
    # inside the molecule. If the target compound label is present, a shorter
    # lower numeric token is not enough evidence to call this a competing final
    # compound.
    if conflict_value < target_value:
        if len(conflict_num.group(0)) < len(target_num.group(0)):
            return True
        if target_value <= 30 and conflict_value <= 10:
            return True
    if conflict_value <= 20:
        return conflict_key == "1"
    return target_key.startswith(conflict_key)


def _has_table_row_evidence(binding: dict[str, Any]) -> bool:
    rule = str(binding.get("binding_rule") or "")
    if rule not in {
        "structure_table_row_order",
        "structure_table_row_order_inferred",
        "structure_table_row_order_corrected",
        "cmpd_overview_table_order",
    }:
        return False
    try:
        return float(binding.get("struct_area") or 0) >= 6000
    except (ValueError, TypeError, OverflowError):
        return False


def _has_nearby_exact_product_label(
    target_key: str, binding: dict[str, Any] | None
) -> bool:
    if not target_key or not binding:
        return False
    exact_key = _label_key(binding.get("nearby_exact_product_label"))
    if exact_key == target_key:
        return True
    source = str(binding.get("visible_label_crop_source") or "")
    if source and source not in VISUAL_LABEL_SOURCES:
        return False
    return bool(
        binding.get("product_context_nearby") is True
        and _int_or_default(binding.get("product_context_distance"), 999) <= 1
        and _label_key(binding.get("visible_label")) == target_key
        and not bool(binding.get("visible_label_multi_candidate"))
    )


def _is_internal_annotation_conflict(
    target_key: str,
    conflict_key: str,
    strict_labels: set[str],
    binding: dict[str, Any] | None = None,
) -> bool:
    """Ignore internal labels that are not competing compound IDs.

    Crops such as "Cpd-5" often also contain an internal "or1" stereochemical
    note. Structure-table rows also include NMR numbers, atom labels, or
    substituent annotations near the drawing while the authoritative compound ID
    is the left column. Keep this narrow: full competing labels still fail
    closed, but short/internal labels no longer override stronger evidence.
    """
    if not target_key:
        return False
    if (
        binding is not None
        and str(binding.get("binding_rule") or "") == "ocr_pair_heading_structure_order"
        and bool(binding.get("pair_heading_sequence_confirmed"))
    ):
        import re

        match = re.fullmatch(r"([1-9]\d*)-([12])", target_key)
        if match:
            base, suffix = match.groups()
            if conflict_key in {base, suffix, f"{base}{suffix}"}:
                return True
    if (
        binding is not None
        and str(binding.get("binding_rule") or "") == "cpd_letter_pair_row_order"
        and bool(binding.get("cpd_letter_pair_sequence_confirmed"))
    ):
        import re

        if re.fullmatch(r"[1-9]\d{0,2}", target_key):
            partner = str(
                binding.get("cpd_letter_pair_partner") or f"{target_key}A"
            ).upper()
            if conflict_key in {target_key, partner, "1"}:
                return True
    if (
        binding is not None
        and str(binding.get("binding_rule") or "")
        == "authoritative_structure_table_sequence"
        and bool(binding.get("authoritative_table_sequence_confirmed"))
    ):
        return bool(conflict_key)
    if binding is not None and str(binding.get("binding_rule") or "") in {
        "visual_grid_label",
        "visual_grid_sequence_order",
    }:
        try:
            target_num = int(__import__("re").match(r"\d+", target_key).group(0))
            conflict_num = int(__import__("re").match(r"\d+", conflict_key).group(0))
            page_min = int(binding.get("visual_grid_page_min") or 0)
            page_max = int(binding.get("visual_grid_page_max") or 0)
        except (ValueError, TypeError, AttributeError, OverflowError):
            target_num = conflict_num = page_min = page_max = 0
        exact_grid_label = target_key in _candidate_labels(binding, strict_only=False)
        sequence_grid_label = bool(binding.get("visual_grid_sequence_confirmed"))
        if (
            (exact_grid_label or sequence_grid_label)
            and page_min
            and page_max
            and page_min <= target_num <= page_max
        ):
            if (
                conflict_num
                and conflict_num < page_min
                and (conflict_num <= 30 or target_num - conflict_num >= 50)
            ):
                return True
            if (
                sequence_grid_label
                and int(binding.get("visual_grid_anchor_count") or 0) >= 6
                and conflict_num
                and page_min <= conflict_num <= page_max
                and abs(conflict_num - target_num) <= 2
            ):
                return True
            if _is_short_internal_annotation(target_key, conflict_key):
                return True
    if _has_nearby_exact_product_label(target_key, binding):
        if _is_short_internal_annotation(target_key, conflict_key):
            return True
        if conflict_key == "1" and target_key != "1":
            return target_key[:1].isdigit()
    if binding is not None and _has_table_row_evidence(binding):
        if conflict_key == "1" and target_key != "1":
            return target_key[:1].isdigit()
        import re

        target_num_match = re.match(r"\d+", target_key)
        conflict_num_match = re.match(r"\d+", conflict_key)
        if target_num_match and conflict_num_match:
            try:
                # In structure tables the authoritative ID is the left column.
                # Strict crop OCR frequently sees atom/procedure labels such as
                # 4/5/7/35A inside otherwise complete product drawings.
                return int(conflict_num_match.group(0)) < int(target_num_match.group(0))
            except (ValueError, TypeError, OverflowError):
                return False
        return _is_short_internal_annotation(target_key, conflict_key)
    if (
        binding is not None
        and str(binding.get("binding_rule") or "")
        in {
            "direct_structure_label",
            "direct_structure_label_merged_fragment",
            "direct_structure_label_right_product_crop",
            "route_title_row_right_product",
            "heading_range_fallback",
        }
        and _has_nearby_exact_product_label(target_key, binding)
    ):
        return _is_short_internal_annotation(target_key, conflict_key)
    if target_key in strict_labels:
        if len(target_key) == 1:
            return False
        if (
            conflict_key.isdigit()
            and target_key.isdigit()
            and int(conflict_key) > int(target_key)
        ):
            return False
        return _is_short_internal_annotation(target_key, conflict_key)
    return False


def _is_truncated_visible_prefix(target_key: str, visible_key: str) -> bool:
    import re

    if not target_key or not visible_key:
        return False
    if not re.fullmatch(r"\d{3}[A-Z]?", target_key):
        return False
    if not re.fullmatch(r"\d{1,2}[A-Z]?", visible_key):
        return False
    return target_key.startswith(visible_key)


def _candidate_labels(
    binding: dict[str, Any], *, strict_only: bool = False
) -> set[str]:
    labels: set[str] = set()
    for candidate in binding.get("visible_label_candidates") or []:
        if not isinstance(candidate, dict):
            continue
        if (
            strict_only
            and str(candidate.get("source") or "") not in STRICT_VISIBLE_SOURCES
        ):
            continue
        key = _label_key(candidate.get("label"))
        if key:
            labels.add(key)
    if not strict_only:
        for label in binding.get("visible_labels") or []:
            key = _label_key(label)
            if key:
                labels.add(key)
        key = _label_key(binding.get("visible_label"))
        if key:
            labels.add(key)
    return labels


def annotate_binding_accuracy(binding: dict[str, Any]) -> dict[str, Any]:
    """Attach patent-agnostic evidence metadata to a binding row.

    A row is confirmed only when its rule is strong and any strict visual label
    evidence agrees with the target compound. Rows without strong evidence stay
    available for debugging but are marked review_required.
    """
    item = dict(binding)
    rule = str(item.get("binding_rule") or "")
    target_key = _label_key(item.get("compound_id") or item.get("cpd"))
    strict_labels = _candidate_labels(item, strict_only=True)
    all_labels = _candidate_labels(item, strict_only=False)
    exact_nearby_product_visual = _has_nearby_exact_product_label(target_key, item)
    reasons: list[str] = []

    strict_multi_labels = strict_labels - {target_key}
    strict_conflicts = sorted(
        label
        for label in strict_labels
        if target_key
        and label != target_key
        and not _is_internal_annotation_conflict(target_key, label, strict_labels, item)
        and not _is_truncated_visible_prefix(target_key, label)
    )
    if strict_conflicts and rule in {
        "direct_structure_label_merged_fragment",
        "direct_structure_label_right_product_crop",
    }:
        item["accuracy_status"] = "review_required"
        item["evidence_tier"] = "conflict"
        item["evidence_reasons"] = [
            f"derived strict crop contains competing labels: {', '.join(strict_conflicts)}"
        ]
        item["fail_closed"] = True
        return item
    if strict_conflicts:
        item["accuracy_status"] = "review_required"
        item["evidence_tier"] = "conflict"
        item["evidence_reasons"] = [
            f"strict visible label conflicts: {', '.join(strict_conflicts)}"
        ]
        item["fail_closed"] = True
        return item

    exact_strict_visual = bool(target_key and target_key in strict_labels)
    exact_any_visual = bool(target_key and target_key in all_labels)
    exact_numbered_cell = (
        rule == "numbered_structure_table_cell" and valid_cell_binding_evidence(item)
    )
    exact_original_heading = (
        rule == "original_heading_standalone" and valid_heading_binding_evidence(item)
    )
    if rule == "original_heading_standalone" and not exact_original_heading:
        item.update(
            accuracy_status="review_required",
            evidence_tier="weak",
            fail_closed=True,
            evidence_reasons=[
                "invalid or incomplete original heading/standalone structure proof"
            ],
        )
        return item
    if rule == "numbered_structure_table_cell" and not exact_numbered_cell:
        item["accuracy_status"] = "review_required"
        item["evidence_tier"] = "weak"
        item["evidence_reasons"] = [
            "invalid or incomplete original structure-table cell evidence"
        ]
        item["fail_closed"] = True
        return item

    if exact_strict_visual:
        reasons.append("exact strict visual label")
    elif exact_nearby_product_visual:
        reasons.append("nearby exact product label")
    elif exact_any_visual:
        reasons.append("exact weak visual label")

    if exact_numbered_cell:
        reasons.append(
            "independently observed ID and unique segment in adjacent original-PDF cell"
        )
    elif exact_original_heading:
        reasons.append(
            "exact original heading and unique standalone diagram before procedure"
        )
    elif rule in {
        "structure_table_row_order",
        "structure_table_row_order_inferred",
        "structure_table_row_order_corrected",
        "cmpd_overview_table_order",
    }:
        reasons.append("left-column structure table row order")
    elif rule == "singleton_claim_formula_structure":
        reasons.append("claim/formula singleton structure")
    elif rule in {
        "direct_structure_label",
        "direct_structure_label_merged_fragment",
        "direct_structure_label_right_product_crop",
        "visual_grid_label",
        "visual_grid_sequence_order",
        "authoritative_structure_table_sequence",
    }:
        if rule == "authoritative_structure_table_sequence":
            reasons.append("complete authoritative structure-table sequence")
        else:
            reasons.append("direct structure label")
    elif rule:
        reasons.append(f"rule={rule}")
    if rule == "ocr_pair_heading_structure_order" and bool(
        item.get("pair_heading_sequence_confirmed")
    ):
        reasons.append("split-pair heading and left/right structure order")
    if rule == "cpd_letter_pair_row_order" and bool(
        item.get("cpd_letter_pair_sequence_confirmed")
    ):
        reasons.append("Cpd-N/Cpd-NA title and left/right structure order")

    geometry_area = float(item.get("struct_area") or 0)
    geometry_width = float(item.get("struct_width") or 0)
    geometry_height = float(item.get("struct_height") or 0)
    geometry_aspect = (
        geometry_width / max(geometry_height, 1.0)
        if geometry_width and geometry_height
        else 0.0
    )
    if geometry_area and geometry_area < 1800:
        item["accuracy_status"] = "review_required"
        item["evidence_tier"] = "weak"
        item["evidence_reasons"] = [
            *reasons,
            "structure crop too small for automatic confirmation",
        ]
        item["fail_closed"] = True
        return item

    if rule == "direct_structure_label_right_product_crop" and (
        geometry_area < 6500 or geometry_aspect > 5.0 or bool(strict_multi_labels)
    ):
        item["accuracy_status"] = "review_required"
        item["evidence_tier"] = "weak"
        item["evidence_reasons"] = [
            *reasons,
            "right-product crop is too small/flat for automatic final-product confirmation",
        ]
        item["fail_closed"] = True
        return item

    if (
        rule == "singleton_claim_formula_structure"
        and target_key == "CLAIM1"
        and geometry_area >= 6000
    ):
        item["accuracy_status"] = "confirmed"
        item["evidence_tier"] = "claim_formula_singleton"
        item["evidence_reasons"] = reasons or ["claim/formula singleton structure"]
        item["fail_closed"] = False
        return item

    if rule in STRONG_BINDING_RULES and (
        exact_numbered_cell
        or exact_original_heading
        or exact_strict_visual
        or exact_nearby_product_visual
        or rule.startswith("structure_table_row_order")
        or (rule == "visual_grid_label" and exact_any_visual)
        or (
            rule == "visual_grid_sequence_order"
            and bool(item.get("visual_grid_sequence_confirmed"))
            and int(item.get("visual_grid_anchor_count") or 0) >= 6
        )
        or (
            rule == "authoritative_structure_table_sequence"
            and bool(item.get("authoritative_table_sequence_confirmed"))
            and int(item.get("authoritative_table_label_count") or 0) >= 6
            and int(item.get("authoritative_table_label_count") or 0)
            == int(item.get("authoritative_table_structure_count") or -1)
        )
        or (
            rule == "ocr_pair_heading_structure_order"
            and bool(item.get("pair_heading_sequence_confirmed"))
        )
        or (
            rule == "cpd_letter_pair_row_order"
            and bool(item.get("cpd_letter_pair_sequence_confirmed"))
        )
    ):
        item["accuracy_status"] = "confirmed"
        item["evidence_tier"] = "strong"
        item["evidence_reasons"] = reasons or ["strong binding rule"]
        item["fail_closed"] = False
        return item

    if rule in STRONG_BINDING_RULES and exact_any_visual:
        item["accuracy_status"] = "review_required"
        item["evidence_tier"] = "medium"
        item["evidence_reasons"] = [*reasons, "visual label is not from a strict crop"]
        item["fail_closed"] = True
        return item

    item["accuracy_status"] = "review_required"
    item["evidence_tier"] = "weak" if rule in REVIEW_BINDING_RULES else "unknown"
    item["evidence_reasons"] = reasons or [
        "insufficient patent-agnostic binding evidence"
    ]
    item["fail_closed"] = True
    return item


def summarise_binding_accuracy(bindings: list[dict[str, Any]]) -> dict[str, Any]:
    confirmed = [b for b in bindings if b.get("accuracy_status") == "confirmed"]
    review = [b for b in bindings if b.get("accuracy_status") != "confirmed"]
    by_tier: dict[str, int] = {}
    for binding in bindings:
        tier = str(binding.get("evidence_tier") or "unknown")
        by_tier[tier] = by_tier.get(tier, 0) + 1
    return {
        "ruleset": ruleset_ref(),
        "total": len(bindings),
        "confirmed": len(confirmed),
        "review_required": len(review),
        "by_tier": by_tier,
        "review_cpds": [b.get("cpd") for b in review[:200]],
    }
