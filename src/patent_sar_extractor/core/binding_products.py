"""Product and reaction-layout strategies using observed labels."""

from __future__ import annotations

import re
from typing import (
    Dict,
    List,
    Optional,
    Tuple,
)

from .binding_candidates import (
    _build_binding_from_structure,
)
from .binding_geometry import (
    _group_structures_by_row,
    _has_cpd_letter_pair_product_text,
    _is_cpd_letter_pair_product_candidate,
)
from .binding_headings import (
    _filter_items_by_focus_windows,
)
from .binding_labels import (
    _BARE_FINAL_LABEL_RE,
    _FINAL_COMPOUND_LABEL_RE,
    _active_label_keys,
    _base_cpd_num,
    _cpd_letter_pair_base_lines,
    _cpd_letter_pair_label_y,
    _cpd_sort_key,
    _labels_near_structure,
    _normalise_compound_label,
    _ocr_confusable_num_pattern,
    _page_text_for_page_no,
    _product_anchor_lines_from_text,
    _split_pair_bases_from_text,
)
from .binding_observations import (
    _normalise_ocr_line_map,
)
from .binding_ocr import (
    _get_ocr_line_coords,
    _get_ocr_word_coords,
)
from .binding_tables import (
    _is_structure_table_layout,
)


def _extract_product_section_bindings(
    processed_structures: List[Dict],
    pages_text: Dict[int, str],
    active_cpds: List[str],
    existing_bindings: List[Dict],
) -> List[Dict]:
    """Bind final products using explicit product subsection text.

    This rule is intentionally stricter than broad heading ranges: it only
    fires around lines that say "化合物 N:" / "化合物 N 的制备" /
    "得到化合物 N", and ignores intermediate sections.
    """
    active_bases = {_base_cpd_num(cpd) for cpd in active_cpds}
    active_bases.discard(None)
    if not active_bases:
        return []

    product_used_structures: set[str] = set()

    by_page: Dict[int, List[Dict]] = {}
    for struct in processed_structures:
        by_page.setdefault(int(struct["page_no"]), []).append(struct)

    bindings: List[Dict] = []
    for page_idx, text in sorted((pages_text or {}).items()):
        page_no = int(page_idx) + 1
        # Product-section evidence is stronger than broad OCR/heading fallbacks.
        # Do not suppress an anchor just because an earlier weak rule already
        # claimed that compound; final merge will choose the stricter rule.
        anchors = _product_anchor_lines_from_text(str(text or ""), active_bases)
        if not anchors:
            continue
        page_structs = list(by_page.get(page_no, []))
        if not page_structs:
            continue
        anchors.sort(key=lambda item: item[1])
        if len(anchors) >= 2:
            rows = _group_structures_by_row(page_structs, y_threshold=90.0)
            multi_rows = [
                row
                for row in rows
                if len(row) >= len(anchors)
                and all(str(p.get("id")) not in product_used_structures for p in row)
            ]
            if multi_rows:
                row = max(
                    multi_rows,
                    key=lambda r: (
                        sum(
                            (float(p.get("x1", 0)) - float(p.get("x0", 0)))
                            * (float(p.get("y1", 0)) - float(p.get("y0", 0)))
                            for p in r
                        ),
                        max(float(p.get("y0") or 0) for p in r),
                    ),
                )
                for (compound_num, _anchor_y, _line), struct in zip(anchors, row):
                    binding = _build_binding_from_structure(struct, str(compound_num))
                    binding["binding_rule"] = "product_section_context"
                    binding["candidates"] = len(row)
                    bindings.append(binding)
                    product_used_structures.add(str(struct.get("id")))
                continue

        for idx, (compound_num, anchor_y, _line) in enumerate(anchors):
            next_y = anchors[idx + 1][1] if idx + 1 < len(anchors) else 10**9
            candidates = [
                p
                for p in page_structs
                if str(p.get("id")) not in product_used_structures
                and float(p.get("y0") or 0) <= anchor_y + 80.0
                and float(p.get("y1") or p.get("y0") or 0) >= max(0.0, anchor_y - 260.0)
                and float(p.get("y0") or 0) < next_y + 20.0
            ]
            if not candidates:
                continue

            def _area(struct: Dict) -> float:
                return max(
                    0.0, float(struct.get("x1", 0)) - float(struct.get("x0", 0))
                ) * max(0.0, float(struct.get("y1", 0)) - float(struct.get("y0", 0)))

            best = max(
                candidates,
                key=lambda p: (_area(p), -abs(float(p.get("y0") or 0) - anchor_y)),
            )
            binding = _build_binding_from_structure(best, str(compound_num))
            binding["binding_rule"] = "product_section_context"
            binding["candidates"] = len(candidates)
            bindings.append(binding)
            product_used_structures.add(str(best.get("id")))

    return bindings


def _product_structures_from_triplets(processed_structures: List[Dict]) -> List[Dict]:
    """For Chinese synthesis pages, DECIMER returns reagent/reagent/product triplets.

    The right-most structure in each row is the target product.
    """
    rows: List[List[Dict]] = []
    for page_no in sorted(set(p["page_no"] for p in processed_structures)):
        page_structs = sorted(
            [p for p in processed_structures if p["page_no"] == page_no],
            key=lambda p: (p["y0"], p["x0"]),
        )
        page_rows: List[List[Dict]] = []
        for struct in page_structs:
            if not page_rows or abs(struct["y0"] - page_rows[-1][0]["y0"]) > 90:
                page_rows.append([struct])
            else:
                page_rows[-1].append(struct)
        rows.extend(page_rows)

    products: List[Dict] = []
    for row in rows:
        if len(row) >= 3:
            products.append(max(row, key=lambda p: p["x0"]))
    return products


def _split_pair_base_lines(
    doc,
    page_no: int,
    page_text: str,
    ocr_line_map: Optional[Dict[int, List[Tuple[float, str]]]] = None,
) -> List[Tuple[int, Optional[float]]]:
    """Return split-product bases with approximate heading y coordinates."""
    lines = (
        (ocr_line_map or {}).get(page_no - 1)
        or _get_ocr_line_coords(doc[page_no - 1])
        or []
    )
    found: List[Tuple[int, Optional[float]]] = []

    for idx, (y0, _text) in enumerate(lines):
        window = " ".join(text for _, text in lines[idx : idx + 3])
        for base in _split_pair_bases_from_text(window):
            if base not in [b for b, _ in found]:
                found.append((base, y0))

    if found:
        return found

    return [(base, None) for base in _split_pair_bases_from_text(page_text)]


def _extract_pair_heading_product_bindings(
    doc,
    pages_text: Dict[int, str],
    processed_structures: List[Dict],
    ocr_line_map: Optional[Dict[int, List[Tuple[float, str]]]] = None,
) -> List[Dict]:
    """Bind split enantiomer pairs from page text plus left/right structure order.

    Tesseract often misreads the tiny label directly under a structure (for
    example 1-2 as 4-2). The nearby heading/title text usually still contains
    the pair as N-1 ... N-2, so use that as the primary source for split pairs.
    """
    bindings: List[Dict] = []
    used_bases: set[int] = set()
    used_structures: set[str] = set()

    for page_no in sorted(set(p["page_no"] for p in processed_structures)):
        page_text = _page_text_for_page_no(pages_text, page_no)
        base_lines = [
            (base, y0)
            for base, y0 in _split_pair_base_lines(
                doc, page_no, page_text, ocr_line_map=ocr_line_map
            )
            if base not in used_bases
        ]
        if not base_lines:
            continue

        page_structs = [
            p
            for p in processed_structures
            if p["page_no"] == page_no and p["id"] not in used_structures
        ]
        rows = _group_structures_by_row(page_structs)
        two_structure_rows = [row for row in rows if len(row) == 2]

        for base, heading_y0 in base_lines:
            available_rows = [
                row
                for row in two_structure_rows
                if all(p["id"] not in used_structures for p in row)
            ]
            if heading_y0 is not None:
                available_rows = [
                    row
                    for row in available_rows
                    if min(float(p["y0"]) for p in row) > heading_y0 + 20
                ]
            if not available_rows:
                continue
            row = min(available_rows, key=lambda r: min(float(p["y0"]) for p in r))
            for suffix, struct in zip(("1", "2"), row):
                binding = _build_binding_from_structure(struct, f"{base}-{suffix}")
                binding["binding_rule"] = "ocr_pair_heading_structure_order"
                binding["pair_heading_sequence_confirmed"] = True
                binding["pair_heading_base"] = int(base)
                binding["pair_heading_suffix"] = suffix
                if heading_y0 is not None:
                    binding["pair_heading_y0"] = float(heading_y0)
                bindings.append(binding)
                used_structures.add(struct["id"])
            used_bases.add(base)

    return bindings


def _extract_cpd_letter_pair_product_bindings(
    pages_text: Dict[int, str],
    processed_structures: List[Dict],
    active_cpds: Optional[List[str]] = None,
    ocr_line_map: Optional[Dict[int, List[Tuple[float, str]]]] = None,
) -> List[Dict]:
    """Bind Cpd-N/Cpd-NA stereoisomer pairs from title text plus row order.

    In Chinese PAMPH-style examples the final scheme often ends with
    precursor -> Cpd-N + Cpd-NA.  The full-page OCR text has the paired title
    reliably, while tight visual OCR can bleed the right label (N-A) onto the
    left product.  For activity-led output we only recover the non-A active row.
    """
    active_keys = _active_label_keys(active_cpds or [])
    if active_cpds and not active_keys:
        return []

    candidates_by_key: Dict[str, List[Tuple[Tuple[int, int, int, int], Dict]]] = {}
    lines_by_page = _normalise_ocr_line_map(ocr_line_map)
    by_page: Dict[int, List[Dict]] = {}
    for struct in processed_structures:
        by_page.setdefault(int(struct.get("page_no") or 0), []).append(struct)

    for page_no in sorted(by_page):
        page_text = _page_text_for_page_no(pages_text, page_no)
        base_lines = _cpd_letter_pair_base_lines(page_no, page_text, lines_by_page)
        if not base_lines:
            continue

        for base, heading_y0 in base_lines:
            key = str(base)
            if active_keys and key not in active_keys:
                continue
            for search_page in (page_no, page_no + 1):
                page_structs = by_page.get(search_page, [])
                if not page_structs:
                    continue
                rows = _group_structures_by_row(page_structs, y_threshold=70.0)
                label_y = _cpd_letter_pair_label_y(base, search_page, lines_by_page)
                has_product_text = _has_cpd_letter_pair_product_text(
                    base,
                    _page_text_for_page_no(pages_text, search_page),
                )
                for row in rows:
                    row_y = min(float(item.get("y0") or 0) for item in row)
                    row_bottom = max(
                        float(item.get("y1") or item.get("y0") or 0) for item in row
                    )
                    if label_y is not None:
                        if row_y > label_y + 12:
                            continue
                        label_distance = abs(float(label_y) - row_bottom)
                    else:
                        if search_page != page_no:
                            continue
                        if heading_y0 is not None and row_y <= float(heading_y0) + 20:
                            continue
                        label_distance = 9999.0
                    complete = [
                        item
                        for item in sorted(
                            row, key=lambda struct: float(struct.get("x0") or 0)
                        )
                        if _is_cpd_letter_pair_product_candidate(item)
                    ]
                    if len(complete) < 2:
                        continue
                    target_struct = complete[-2]
                    binding = _build_binding_from_structure(target_struct, key)
                    binding["binding_rule"] = "cpd_letter_pair_row_order"
                    binding["cpd_letter_pair_sequence_confirmed"] = True
                    binding["cpd_letter_pair_base"] = int(base)
                    binding["cpd_letter_pair_partner"] = f"{base}A"
                    binding["cpd_letter_pair_role"] = "left_non_a_product"
                    if heading_y0 is not None:
                        binding["cpd_letter_pair_heading_y0"] = float(heading_y0)
                    if label_y is not None:
                        binding["cpd_letter_pair_label_y0"] = float(label_y)
                    score = (
                        0 if (label_y is not None or has_product_text) else 1,
                        int(label_distance),
                        abs(search_page - page_no),
                        -int(row_y),
                    )
                    candidates_by_key.setdefault(key, []).append((score, binding))

    bindings: List[Dict] = []
    used_structures: set[str] = set()
    for key in sorted(candidates_by_key, key=_cpd_sort_key):
        for _score, binding in sorted(candidates_by_key[key], key=lambda item: item[0]):
            sid = str(binding.get("structure_id") or "")
            if sid in used_structures:
                continue
            bindings.append(binding)
            used_structures.add(sid)
            break
    return bindings


def _extract_split_reaction_bare_bindings(
    processed_structures: List[Dict],
    existing_bindings: List[Dict],
    used_structures: set[str],
    used_labels: set[str],
) -> List[Dict]:
    """For split pages, bind the starting material N in a later reaction row."""
    bindings: List[Dict] = []
    split_pages: Dict[int, List[int]] = {}
    for binding in existing_bindings:
        m = re.match(r"^Compound\s+([1-9]\d*)-[12]$", binding["cpd"])
        if not m:
            continue
        split_pages.setdefault(binding["page_no"], [])
        base = int(m.group(1))
        if base not in split_pages[binding["page_no"]]:
            split_pages[binding["page_no"]].append(base)

    for page_no, bases in split_pages.items():
        page_rows = _group_structures_by_row(
            [p for p in processed_structures if p["page_no"] == page_no]
        )
        pair_min_y_by_base = {}
        for base in bases:
            pair_rows = [
                float(b["struct_y0"])
                for b in existing_bindings
                if b["page_no"] == page_no
                and b["cpd"] in (f"Compound {base}-1", f"Compound {base}-2")
            ]
            if pair_rows:
                pair_min_y_by_base[base] = min(pair_rows)

        for base in bases:
            label = str(base)
            if label in used_labels:
                continue
            min_pair_y = pair_min_y_by_base.get(base)
            if min_pair_y is None:
                continue
            candidate_rows = [
                row
                for row in page_rows
                if len(row) >= 2
                and min(float(p["y0"]) for p in row) > min_pair_y + 60
                and all(p["id"] not in used_structures for p in row)
            ]
            if not candidate_rows:
                continue
            row = min(candidate_rows, key=lambda r: min(float(p["y0"]) for p in r))
            struct = row[0]
            binding = _build_binding_from_structure(struct, label)
            binding["binding_rule"] = "split_reaction_starting_material"
            bindings.append(binding)
            used_labels.add(label)
            used_structures.add(struct["id"])

    return bindings


def _extract_paired_route_product_bindings(
    processed_structures: List[Dict],
    pages_text: Dict[int, str],
    active_cpds: List[str],
    existing_bindings: List[Dict],
) -> List[Dict]:
    """Bind paired final products from a shared route scheme.

    Chinese patents often show "实施例24、25 / 化合物24、25" as one route:
    two product rows are drawn on the page before the text procedures continue
    on the next page. OCR may miss the tiny labels under the structures, so use
    the explicit paired title plus top-to-bottom product rows. This is kept
    narrow to avoid treating intermediate-heavy route rows as final products.
    """
    active_bases = {_base_cpd_num(cpd) for cpd in active_cpds}
    active_bases.discard(None)
    if not active_bases:
        return []

    used_structure_ids = {
        str(binding.get("structure_id"))
        for binding in existing_bindings
        if binding.get("structure_id")
    }
    existing_base_nums = {
        _base_cpd_num(binding.get("cpd", "")) for binding in existing_bindings
    }
    existing_base_nums.discard(None)

    bindings: List[Dict] = []
    for page_no in sorted(set(p["page_no"] for p in processed_structures)):
        page_text = _page_text_for_page_no(pages_text, page_no, include_next=True)
        if not page_text:
            continue
        text_one_line = re.sub(r"\s+", " ", page_text)
        pair_matches: List[Tuple[str, str]] = []
        for base in sorted(active_bases):
            right = base + 1
            if right not in active_bases:
                continue
            left_pat = _ocr_confusable_num_pattern(base)
            right_pat = _ocr_confusable_num_pattern(right)
            if re.search(
                rf"(?:实施例|化.?[合台]物)\s*{left_pat}\s*[、,，]\s*{right_pat}(?![\dA-Za-z-])",
                text_one_line,
                re.IGNORECASE,
            ):
                pair_matches.append((str(base), str(right)))
        pairs = []
        for left, right in pair_matches:
            nums = (int(left), int(right))
            if nums[1] != nums[0] + 1:
                continue
            if nums[0] not in active_bases or nums[1] not in active_bases:
                continue
            if nums[0] in existing_base_nums and nums[1] in existing_base_nums:
                continue
            pairs.append(nums)
        if not pairs:
            continue

        page_structs = [
            p
            for p in processed_structures
            if p["page_no"] == page_no and str(p["id"]) not in used_structure_ids
        ]
        if len(page_structs) < 4:
            continue
        rows = _group_structures_by_row(page_structs, y_threshold=70.0)
        product_rows = [
            row
            for row in rows
            if len(row) >= 2
            and max(float(p["x1"]) for p in row) >= 430.0
            and max(float(p["y1"]) - float(p["y0"]) for p in row) >= 35.0
        ]
        if len(product_rows) < 2:
            continue
        product_rows = sorted(
            product_rows, key=lambda row: min(float(p["y0"]) for p in row)
        )

        for nums in pairs:
            if len(product_rows) < 2:
                break
            for compound_num, row in zip(nums, product_rows[-2:]):
                if compound_num in existing_base_nums:
                    continue
                struct = max(row, key=lambda p: (float(p["x1"]), float(p["x0"])))
                binding = _build_binding_from_structure(struct, str(compound_num))
                binding["binding_rule"] = "paired_route_product_row_order"
                binding["candidates"] = len(row)
                bindings.append(binding)
                used_structure_ids.add(struct["id"])
                existing_base_nums.add(compound_num)

    return bindings


def _extract_triplet_split_row_bindings(
    doc,
    processed_structures: List[Dict],
    used_structures: set[str],
    used_labels: set[str],
    word_cache: Optional[Dict[int, List[Dict]]] = None,
    focus_windows: Optional[Dict[int, List[Tuple[float, float]]]] = None,
) -> List[Dict]:
    """Bind rows laid out as N -> N-1 + N-2 when OCR drops the middle hyphen."""
    bindings: List[Dict] = []

    for page_no in sorted(set(p["page_no"] for p in processed_structures)):
        if page_no < 1 or page_no > len(doc):
            continue
        page_structs = [
            p
            for p in processed_structures
            if p["page_no"] == page_no and p["id"] not in used_structures
        ]
        page_structs = _filter_items_by_focus_windows(
            page_structs, (focus_windows or {}).get(page_no), margin=60.0
        )
        rows = _group_structures_by_row(page_structs)
        words = _get_ocr_word_coords(doc[page_no - 1], cache=word_cache)
        words = _filter_items_by_focus_windows(
            words, (focus_windows or {}).get(page_no), margin=80.0
        )
        if not words:
            continue

        for row in rows:
            if len(row) < 3 or any(p["id"] in used_structures for p in row[:3]):
                continue
            left_labels = _labels_near_structure(words, row[0])
            right_labels = _labels_near_structure(words, row[2])
            bases = [
                int(label)
                for label in left_labels
                if _BARE_FINAL_LABEL_RE.fullmatch(label)
            ]
            for base in bases:
                if f"{base}-2" not in right_labels:
                    continue
                labels = [str(base), f"{base}-1", f"{base}-2"]
                if any(label in used_labels for label in labels):
                    continue
                for struct, label in zip(row[:3], labels):
                    binding = _build_binding_from_structure(struct, label)
                    binding["binding_rule"] = "triplet_split_row_structure_order"
                    bindings.append(binding)
                    used_labels.add(label)
                    used_structures.add(struct["id"])
                break

    return bindings


def _extract_first_dense_scheme_product(
    processed_structures: List[Dict],
    existing_bindings: List[Dict],
    used_structures: set[str],
    used_labels: set[str],
) -> List[Dict]:
    """Recover Compound 1 from dense multi-step route pages without readable labels."""
    if "1" in used_labels:
        return []
    has_split_1 = any(
        b["cpd"] in ("Compound 1-1", "Compound 1-2") for b in existing_bindings
    )
    if not has_split_1:
        return []

    for page_no in sorted(set(p["page_no"] for p in processed_structures)):
        page_structs = [
            p
            for p in processed_structures
            if p["page_no"] == page_no and p["id"] not in used_structures
        ]
        if len(page_structs) < 8:
            continue
        rows = _group_structures_by_row(page_structs)
        candidate_rows = [row for row in rows if len(row) >= 2]
        if not candidate_rows:
            continue
        row = max(candidate_rows, key=lambda r: max(float(p["y0"]) for p in r))
        struct = max(row, key=lambda p: float(p["x0"]))
        binding = _build_binding_from_structure(struct, "1")
        binding["binding_rule"] = "dense_scheme_final_product"
        used_labels.add("1")
        used_structures.add(struct["id"])
        return [binding]

    return []


def _extract_bare_product_label_bindings(
    doc,
    processed_structures: List[Dict],
    used_structures: set[str],
    used_labels: set[str],
    pages_text: Optional[Dict[int, str]] = None,
    word_cache: Optional[Dict[int, List[Dict]]] = None,
    focus_windows: Optional[Dict[int, List[Tuple[float, float]]]] = None,
) -> List[Dict]:
    """Bind bare-number final products without accepting every numeric label.

    Bare labels like "1" or "8" are valid final products in Chinese synthesis
    pages, but similar labels also appear under intermediates. Restrict this
    rule to isolated structures and the right-most structure in reaction rows.
    """
    bindings: List[Dict] = []
    active_bases = {_base_cpd_num(cpd) for cpd in (used_labels or [])}
    active_bases.discard(None)
    product_context_bases_by_page: Dict[int, set[int]] = {}
    for page_idx, text in (pages_text or {}).items():
        page_no_ctx = (
            int(page_idx) + 1 if isinstance(page_idx, int) else int(page_idx) + 1
        )
        anchors = _product_anchor_lines_from_text(str(text or ""), set(range(1, 301)))
        if anchors:
            product_context_bases_by_page[page_no_ctx] = {
                num for num, _y, _line in anchors
            }

    for page_no in sorted(set(p["page_no"] for p in processed_structures)):
        if page_no < 1 or page_no > len(doc):
            continue
        page_text = _page_text_for_page_no(pages_text, page_no)
        page_structs = [
            p
            for p in processed_structures
            if p["page_no"] == page_no and p["id"] not in used_structures
        ]
        if _is_structure_table_layout(
            page_structs, page_text, active_bases=active_bases
        ):
            continue
        page_structs = _filter_items_by_focus_windows(
            page_structs, (focus_windows or {}).get(page_no), margin=60.0
        )
        rows = _group_structures_by_row(page_structs)
        candidate_structs = []
        for row in rows:
            if len(row) == 1:
                candidate_structs.append(row[0])
            elif len(row) >= 2:
                candidate_structs.append(row[-1])

        words = _get_ocr_word_coords(doc[page_no - 1], cache=word_cache)
        words = _filter_items_by_focus_windows(
            words, (focus_windows or {}).get(page_no), margin=80.0
        )
        if not words:
            continue

        for struct in candidate_structs:
            if struct["id"] in used_structures:
                continue
            x0, x1 = float(struct["x0"]), float(struct.get("x1", struct["x0"]))
            y0, y1 = float(struct["y0"]), float(struct.get("y1", struct["y0"]))
            cx = (x0 + x1) / 2
            width = max(25.0, x1 - x0)

            candidates = []
            has_hyphen_label_nearby = False
            for word in words:
                label = _normalise_compound_label(word["text"])
                dx = abs(float(word["x"]) - cx)
                y = float(word["y"])
                below = y1 - 5 <= y <= y1 + 55
                inside_or_above_bottom = y0 <= y <= y1 + 20
                near_structure = dx <= max(width * 0.55, 35.0) and (
                    below or inside_or_above_bottom
                )
                if near_structure and _FINAL_COMPOUND_LABEL_RE.fullmatch(label):
                    has_hyphen_label_nearby = True
                if not _BARE_FINAL_LABEL_RE.fullmatch(label):
                    continue
                if near_structure:
                    dy = abs(y - y1) if below else abs(y - y0)
                    candidates.append((dy + dx * 0.05, label, word))

            if has_hyphen_label_nearby:
                continue
            if not candidates:
                continue
            _, label, _word = min(candidates, key=lambda x: x[0])
            if label in used_labels:
                continue
            used_labels.add(label)
            used_structures.add(struct["id"])
            binding = _build_binding_from_structure(struct, label)
            binding["binding_rule"] = "ocr_bare_numeric_product_label"
            bindings.append(binding)

    return bindings
