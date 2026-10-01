"""Evidence-preserving fragment crop and same-row strategies."""

from __future__ import annotations

import logging
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

from .binding_candidates import (
    _active_ordered_bindings,
    _build_binding_from_structure,
    _is_low_internal_label_in_multi_visible_crop,
    _visible_label_conflict_rank,
    _visual_binding_priority,
)
from .binding_geometry import (
    _attach_structure_geometry,
    _group_structures_by_row,
    _is_complete_product_like_structure,
    _is_ocsr_single_molecule_source,
    _right_complete_product_on_same_row,
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
    _normalise_compound_label,
    _passes_exact_visual_label_guard,
    _product_context_distance,
    _strict_visible_label_keys_for_binding,
    _visible_label_keys_for_binding,
)
from .binding_observations import (
    _annotate_bindings_with_visible_labels,
    _labels_from_visible_cache_item,
    _normalise_ocr_line_map,
    _normalise_visible_cache_item,
)

logger = logging.getLogger(__name__)


def _has_other_active_strict_label(
    struct: Dict, target_key: str, visible_label_cache: Optional[Dict[str, Dict]]
) -> bool:
    sid = str(struct.get("id") or "")
    for candidate in _normalise_visible_cache_item(
        (visible_label_cache or {}).get(sid)
    ):
        source = str(candidate.get("source") or "")
        if source not in _STRICT_VISIBLE_LABEL_SOURCES:
            continue
        key = _cpd_label_key(str(candidate.get("label") or ""))
        if key and key != target_key:
            return True
    return False


def _is_mergeable_fragment_neighbor(
    current: Dict,
    neighbor: Dict,
    target_key: str,
    visible_label_cache: Optional[Dict[str, Dict]],
) -> bool:
    """Return True when adjacent DECIMER boxes look like one split molecule."""
    if int(current.get("page_no") or 0) != int(neighbor.get("page_no") or 0):
        return False
    if _has_other_active_strict_label(neighbor, target_key, visible_label_cache):
        return False

    cy0, cy1 = float(current.get("y0") or 0), float(current.get("y1") or 0)
    ny0, ny1 = float(neighbor.get("y0") or 0), float(neighbor.get("y1") or 0)
    overlap = max(0.0, min(cy1, ny1) - max(cy0, ny0))
    min_height = max(1.0, min(cy1 - cy0, ny1 - ny0))
    if overlap / min_height < 0.55:
        return False

    gap = max(float(neighbor.get("x0") or 0), float(current.get("x0") or 0)) - min(
        float(neighbor.get("x1") or 0),
        float(current.get("x1") or 0),
    )
    if gap < -8 or gap > 90:
        return False
    return True


def _save_merged_structure_crop(
    parts: List[Dict], output_dir: str, target_key: str
) -> Optional[Tuple[str, Dict[str, Any]]]:
    """Save a page-image crop covering split structure parts and return geometry."""
    if not parts:
        return None
    raw_boxes = []
    for part in parts:
        raw = part.get("struct") or {}
        bbox = raw.get("bbox") or []
        if len(bbox) != 4:
            return None
        raw_boxes.append([int(round(float(v))) for v in bbox])
    image_path = str(parts[0].get("image_path") or "")
    page_no = int(parts[0].get("page_no") or 0)
    page_image = Path(image_path).with_name(f"page_{page_no:03d}.png")
    if not page_image.is_file():
        return None
    try:
        from PIL import Image

        img = Image.open(page_image).convert("RGB")
        left = max(0, min(box[0] for box in raw_boxes) - 8)
        top = max(0, min(box[1] for box in raw_boxes) - 10)
        right = min(img.width, max(box[2] for box in raw_boxes) + 8)
        bottom = min(img.height, max(box[3] for box in raw_boxes) + 24)
        if right - left <= 10 or bottom - top <= 10:
            return None
        crop = img.crop((left, top, right, bottom))
        merged_dir = Path(output_dir) / "merged_fragments"
        merged_dir.mkdir(parents=True, exist_ok=True)
        part_ids = "_".join(str(part.get("id") or "") for part in parts)
        path = merged_dir / f"{part_ids}_compound_{target_key}.png"
        crop.save(path)
    except Exception as exc:
        logger.debug("Split-fragment crop save failed: %s", exc)
        return None

    scale = 72 / 150
    geom = {
        "struct_x0": left * scale,
        "struct_y0": top * scale,
        "struct_x1": right * scale,
        "struct_y1": bottom * scale,
        "struct_width": (right - left) * scale,
        "struct_height": (bottom - top) * scale,
        "struct_area": ((right - left) * scale) * ((bottom - top) * scale),
        "struct_aspect": (right - left) / max((bottom - top), 1),
    }
    return str(path), geom


def _merge_split_visible_label_fragments(
    final_bindings: List[Dict],
    processed_structures: List[Dict],
    active_cpds: List[str],
    visible_label_cache: Optional[Dict[str, Dict]],
    output_dir: str,
) -> List[Dict]:
    """Merge adjacent DECIMER fragments when the label-bearing crop is incomplete."""
    if not final_bindings or not processed_structures:
        return final_bindings

    active_keys = _active_label_keys(active_cpds)
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

    merged: List[Dict] = []
    replacements = 0
    for binding in _annotate_bindings_with_visible_labels(
        final_bindings, visible_label_cache
    ):
        item = dict(binding)
        key = _binding_label_key(item)
        sid = str(item.get("source_structure_id") or item.get("structure_id") or "")
        struct = struct_by_id.get(sid)
        if (
            not key
            or key not in active_keys
            or not struct
            or key not in _strict_visible_label_keys_for_binding(item)
            or _is_complete_product_like_structure(item)
        ):
            merged.append(item)
            continue

        geom = _structure_geometry(item)
        if (
            geom["struct_area"] >= 4200
            and geom["struct_width"] >= 60
            and geom["struct_height"] >= 55
        ):
            merged.append(item)
            continue

        row = next(
            (
                row
                for row in rows_by_page.get(int(struct.get("page_no") or 0), [])
                if any(str(part.get("id") or "") == sid for part in row)
            ),
            [],
        )
        if not row:
            merged.append(item)
            continue

        parts = [struct]
        current_left = float(struct.get("x0") or 0)
        current_right = float(struct.get("x1") or 0)
        for neighbor in row:
            nsid = str(neighbor.get("id") or "")
            if nsid == sid:
                continue
            if not _is_mergeable_fragment_neighbor(
                struct, neighbor, key, visible_label_cache
            ):
                continue
            nx0, nx1 = float(neighbor.get("x0") or 0), float(neighbor.get("x1") or 0)
            if nx1 <= current_left + 6 or nx0 >= current_right - 6:
                parts.append(neighbor)
        parts = sorted(parts, key=lambda part: float(part.get("x0") or 0))
        if len(parts) <= 1:
            merged.append(item)
            continue

        saved = _save_merged_structure_crop(parts, output_dir, key)
        if not saved:
            merged.append(item)
            continue
        path, merged_geom = saved
        item["image_path"] = path
        item["source_image_path"] = str(
            item.get("source_image_path") or struct.get("image_path") or ""
        )
        item["ocsr_image_path"] = str(path)
        item["structure_id"] = f"{sid}_merged"
        item["source_structure_id"] = sid
        item["binding_rule"] = "direct_structure_label_merged_fragment"
        item["merged_fragment_sources"] = [str(part.get("id") or "") for part in parts]
        item.update(merged_geom)
        merged.append(item)
        replacements += 1

    if replacements:
        logger.info("   🧩 合并严格可见标签的拆分结构图块: %d rows", replacements)
    return _active_ordered_bindings(merged, active_cpds)


def _save_expanded_strict_label_crop(
    struct: Dict,
    row: List[Dict],
    output_dir: str,
    target_key: str,
) -> Optional[Tuple[str, Dict[str, Any]]]:
    """Expand a strict label-bearing fragment to its visual row cell.

    DECIMER can split a labelled final product into a lower fragment that still
    carries the printed compound number.  The repair crop must recover the full
    molecule, but it must not swallow neighboring reaction arrows, plus signs, or
    the prose below the drawing.  Use the nearest same-row structure gaps as
    visual cell boundaries, then expand mostly upward from the label fragment.
    """
    raw = struct.get("struct") or {}
    bbox = raw.get("bbox") or []
    if len(bbox) != 4:
        return None
    image_path = str(struct.get("image_path") or "")
    page_no = int(struct.get("page_no") or 0)
    page_image = Path(image_path).with_name(f"page_{page_no:03d}.png")
    if not page_image.is_file():
        return None

    try:
        from PIL import Image

        img = Image.open(page_image).convert("RGB")
        x0, y0, x1, y1 = [int(round(float(v))) for v in bbox]
        row_sorted = sorted(
            row or [struct], key=lambda item: float(item.get("x0") or 0)
        )
        idx = next(
            (
                i
                for i, item in enumerate(row_sorted)
                if str(item.get("id") or "") == str(struct.get("id") or "")
            ),
            -1,
        )
        width = max(1, x1 - x0)
        height = max(1, y1 - y0)
        left = x0 - max(42, int(width * 0.62))
        right = x1 + max(18, int(width * 0.26))
        if width < 170 and height < 230:
            # A strict label can be attached to a DECIMER half-module when the
            # left heterocycle or right substituent is segmented separately.
            # Recover the full visual cell, not only the label-bearing half.
            left = min(left, x0 - max(56, int(width * 0.86)))
            right = max(right, x1 + max(34, int(width * 0.42)))
        if idx > 0:
            prev_raw = (row_sorted[idx - 1].get("struct") or {}).get("bbox") or []
            if len(prev_raw) == 4:
                px1 = int(round(float(prev_raw[2])))
                gap = x0 - px1
                if gap > 20:
                    # Stay inside the product's visual cell; the left side of a
                    # split product often borders a reaction arrow.
                    left = max(left, px1 + int(gap * 0.68))
        if idx >= 0 and idx + 1 < len(row_sorted):
            next_raw = (row_sorted[idx + 1].get("struct") or {}).get("bbox") or []
            if len(next_raw) == 4:
                nx0 = int(round(float(next_raw[0])))
                gap = nx0 - x1
                if gap > 20:
                    # Keep away from neighboring products/plus signs while
                    # retaining terminal substituents near the label fragment.
                    right = min(right, x1 + int(gap * 0.28))

        top = y0 - max(58, int(height * 1.08))
        if width < 170 and height < 230:
            top = min(top, y0 - max(70, int(height * 1.22)))
        bottom = y1 + max(18, int(height * 0.24))
        left = max(0, left)
        top = max(0, top)
        right = min(img.width, right)
        bottom = min(img.height, bottom)
        expanded_enough = (
            right - left > width * 1.35
            or bottom - top > height * 1.35
            or (
                width < 170
                and height < 230
                and right - left > width * 1.18
                and bottom - top > height * 1.18
            )
        )
        if not expanded_enough:
            return None
        crop = img.crop((left, top, right, bottom))
        expanded_dir = Path(output_dir) / "expanded_strict_labels"
        expanded_dir.mkdir(parents=True, exist_ok=True)
        path = expanded_dir / f"{struct.get('id')}_compound_{target_key}_expanded.png"
        crop.save(path)
    except Exception as exc:
        logger.debug("Strict-label expanded crop save failed: %s", exc)
        return None

    scale = 72 / 150
    geom = {
        "struct_x0": left * scale,
        "struct_y0": top * scale,
        "struct_x1": right * scale,
        "struct_y1": bottom * scale,
        "struct_width": (right - left) * scale,
        "struct_height": (bottom - top) * scale,
        "struct_area": ((right - left) * scale) * ((bottom - top) * scale),
        "struct_aspect": (right - left) / max((bottom - top), 1),
    }
    return str(path), geom


def _repair_weak_bindings_with_expanded_strict_fragments(
    final_bindings: List[Dict],
    processed_structures: List[Dict],
    active_cpds: List[str],
    pages_text: Dict[int, str],
    visible_label_cache: Optional[Dict[str, Dict]],
    output_dir: str,
    ocr_line_map: Optional[Dict[int, List[Any]]] = None,
) -> List[Dict]:
    """Use strict visible labels to recover complete crops for split fragments."""
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

    weak_rules = {
        "heading_range_fallback",
        "product_section_context",
        "paired_route_product_row_order",
        "triplet_split_row_structure_order",
        "split_reaction_product_label",
        "ocr_numeric_structure_label",
        "ocr_bare_numeric_product_label",
        "dense_scheme_final_product",
        "same_row_right_product_repair",
        "route_title_row_right_product",
    }
    target_keys = set()
    for key in active_keys:
        current = by_key.get(key)
        if not current:
            target_keys.add(key)
            continue
        rule = str(current.get("binding_rule") or "")
        geom = _structure_geometry(current)
        strict_exact = key in _strict_visible_label_keys_for_binding(current)
        current_visible_keys = _visible_label_keys_for_binding(current)
        current_is_clean_standalone = (
            rule == "direct_structure_label"
            and key in current_visible_keys
            and current_visible_keys <= {key}
            and _is_ocsr_single_molecule_source(current)
            and not _is_low_internal_label_in_multi_visible_crop(current)
            and _visible_label_conflict_rank(current, active_keys) < 3
        )
        if current_is_clean_standalone:
            # A wide/weak OCR label on a complete standalone product is safer
            # than a strict label attached to a later reaction intermediate.
            continue
        if (
            rule in weak_rules
            or not strict_exact
            or geom["struct_area"] < 4200
            or (
                key in {"1", "2", "3", "4", "5", "6", "7", "8", "9"}
                and geom["struct_area"] < 6400
                and geom["struct_height"] < 95
            )
        ):
            target_keys.add(key)
    if not target_keys:
        return final_bindings

    candidates_by_key: Dict[str, List[Tuple[Tuple[int, int, int, int], Dict]]] = {}
    for sid, cache_item in (visible_label_cache or {}).items():
        struct = struct_by_id.get(str(sid))
        if not struct:
            continue
        strict_candidates = [
            candidate
            for candidate in _normalise_visible_cache_item(cache_item)
            if str(candidate.get("source") or "") in _STRICT_VISIBLE_LABEL_SOURCES
            and _cpd_label_key(str(candidate.get("label") or "")) in target_keys
        ]
        if not strict_candidates:
            continue
        page_no = int(struct.get("page_no") or 0)
        row = next(
            (
                row
                for row in rows_by_page.get(page_no, [])
                if any(str(item.get("id") or "") == str(sid) for item in row)
            ),
            [struct],
        )
        for candidate in strict_candidates:
            label = _normalise_compound_label(str(candidate.get("label") or ""))
            key = _cpd_label_key(label)
            if key not in target_keys:
                continue
            ok_exact, exact_label = _passes_exact_visual_label_guard(
                struct,
                key,
                lines_by_page,
                row=row,
            )
            if not ok_exact:
                continue
            context_distance = _product_context_distance(
                pages_text, page_no, _base_cpd_num(key) or 0
            )
            if context_distance > 1:
                continue
            saved = _save_expanded_strict_label_crop(struct, row, output_dir, key)
            if not saved:
                continue
            path, expanded_geom = saved
            binding = _build_binding_from_structure(struct, key)
            binding["binding_rule"] = "direct_structure_label_merged_fragment"
            binding["visible_label"] = label
            binding["visual_label_source"] = "expanded_strict_label"
            binding["visible_label_crop_source"] = str(candidate.get("source") or "")
            binding["visible_label_multi_candidate"] = False
            binding["product_context_nearby"] = True
            binding["product_context_distance"] = int(context_distance)
            binding["source_structure_id"] = str(sid)
            binding["structure_id"] = f"{sid}_expanded"
            binding["image_path"] = path
            binding["source_image_path"] = str(struct.get("image_path") or "")
            source_is_clean = _is_ocsr_single_molecule_source(struct)
            binding["ocsr_source_clean_single_molecule"] = source_is_clean
            binding["ocsr_image_path"] = str(
                struct.get("image_path") if source_is_clean else path
            )
            binding["expanded_from_fragment"] = str(sid)
            binding["visible_labels"] = _labels_from_visible_cache_item(cache_item)
            binding["visible_label_candidates"] = _normalise_visible_cache_item(
                cache_item
            )
            if exact_label:
                binding["nearby_exact_product_label"] = exact_label
            binding.update(expanded_geom)
            score = (
                _VISIBLE_LABEL_SOURCE_RANK.get(str(candidate.get("source") or ""), 99),
                int(context_distance),
                _visual_module_score(
                    {
                        **struct,
                        **{
                            "x0": expanded_geom["struct_x0"],
                            "y0": expanded_geom["struct_y0"],
                            "x1": expanded_geom["struct_x1"],
                            "y1": expanded_geom["struct_y1"],
                        },
                    }
                )[0],
                -int(expanded_geom["struct_area"]),
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
        logger.info("   🧩 严格可见标签扩展修复弱/片段绑定: %d rows", replacements)
    return _active_ordered_bindings(list(by_key.values()), active_cpds)


def _replace_with_expanded_strict_crops(
    final_bindings: List[Dict],
    output_dir: str,
) -> List[Dict]:
    """Use saved strict-label expanded crops for SMILES/final output."""
    if not final_bindings:
        return final_bindings
    expanded_dir = Path(output_dir) / "expanded_strict_labels"
    if not expanded_dir.is_dir():
        return final_bindings
    replaced = 0
    updated: List[Dict] = []
    for binding in final_bindings:
        item = dict(binding)
        key = _binding_label_key(item)
        sid = str(item.get("source_structure_id") or item.get("structure_id") or "")
        if not key or not sid:
            updated.append(item)
            continue
        path = expanded_dir / f"{sid}_compound_{key}_expanded.png"
        if not path.is_file():
            updated.append(item)
            continue
        if _is_complete_product_like_structure(
            {
                "x0": item.get("struct_x0"),
                "x1": item.get("struct_x1"),
                "y0": item.get("struct_y0"),
                "y1": item.get("struct_y1"),
            }
        ) and str(item.get("binding_rule") or "") in {
            "direct_structure_label",
            "route_title_row_right_product",
        }:
            updated.append(item)
            continue
        try:
            from PIL import Image

            img = Image.open(path)
            width_px, height_px = img.size
            scale = 72 / 150
            item["struct_width"] = width_px * scale
            item["struct_height"] = height_px * scale
            item["struct_area"] = item["struct_width"] * item["struct_height"]
            item["struct_aspect"] = width_px / max(height_px, 1)
        except Exception:
            pass
        item["display_image_path"] = str(
            item.get("display_image_path")
            or item.get("source_image_path")
            or item.get("image_path")
            or path
        )
        item["image_path"] = str(
            item.get("source_image_path") or item.get("image_path") or path
        )
        item["source_structure_id"] = sid
        item["structure_id"] = f"{sid}_expanded"
        item["expanded_from_fragment"] = sid
        item["source_image_path"] = str(item.get("source_image_path") or "")
        item["ocsr_image_path"] = str(
            item.get("ocsr_image_path") or item.get("source_image_path") or path
        )
        if str(item.get("binding_rule") or "") == "direct_structure_label":
            item["binding_rule"] = "direct_structure_label_merged_fragment"
        replaced += 1
        updated.append(item)
    if replaced:
        logger.info("   🧩 使用严格可见标签扩展图作为最终结构: %d rows", replaced)
    return updated


def _repair_same_row_fragment_bindings_to_right_product(
    final_bindings: List[Dict],
    processed_structures: List[Dict],
    active_cpds: List[str],
    visible_label_cache: Optional[Dict[str, Dict]] = None,
) -> List[Dict]:
    """Move fallback/table bindings from route fragments to the right-side product."""
    if not final_bindings or not processed_structures:
        return final_bindings
    repair_rules = {
        "heading_range_fallback",
        "structure_table_row_order",
        "structure_table_row_order_inferred",
        "structure_table_row_order_corrected",
        "cmpd_overview_table_order",
        "heading_row_right_product_recovery",
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
    used_structures = {
        str(binding.get("source_structure_id") or binding.get("structure_id") or "")
        for binding in final_bindings
    }
    repaired: List[Dict] = []
    replacements = 0
    for binding in final_bindings:
        item = dict(binding)
        if str(item.get("binding_rule") or "") not in repair_rules:
            repaired.append(item)
            continue
        sid = str(item.get("source_structure_id") or item.get("structure_id") or "")
        struct = struct_by_id.get(sid)
        if not struct:
            repaired.append(item)
            continue
        replacement = _right_complete_product_on_same_row(
            struct, rows_by_page, min_area_ratio=1.05
        )
        if not replacement:
            repaired.append(item)
            continue
        replacement_sid = str(replacement.get("id") or "")
        if replacement_sid in used_structures and replacement_sid != sid:
            repaired.append(item)
            continue
        item["structure_id"] = replacement_sid
        item["source_structure_id"] = replacement_sid
        item["page_no"] = replacement["page_no"]
        item["structure_index"] = replacement["idx"]
        item["struct_x0"] = replacement["x0"]
        item["struct_y0"] = replacement["y0"]
        item["image_path"] = replacement["image_path"]
        item["source_image_path"] = str(
            replacement.get("image_path") or item.get("source_image_path") or ""
        )
        item["ocsr_image_path"] = str(
            replacement.get("image_path") or item.get("ocsr_image_path") or ""
        )
        item["binding_rule"] = "same_row_right_product_repair"
        item["same_row_fragment_repaired_from"] = sid
        _attach_structure_geometry(item, replacement)
        repaired.append(item)
        used_structures.discard(sid)
        used_structures.add(replacement_sid)
        replacements += 1
    if replacements:
        logger.info("   🧭 同行右侧完整产物替换中间体/片段绑定: %d rows", replacements)
    return _active_ordered_bindings(
        _annotate_bindings_with_visible_labels(repaired, visible_label_cache),
        active_cpds,
    )
