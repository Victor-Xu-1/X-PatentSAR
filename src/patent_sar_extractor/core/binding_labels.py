"""Pure label, source-kind and original-text interpretation."""

from __future__ import annotations

import logging
import re
from typing import (
    Any,
)

logger = logging.getLogger(__name__)
from .activity_identity import printed_identifier_key

_INTERMEDIATE_RE = re.compile(r"^Intermediate", re.IGNORECASE)


_FINAL_COMPOUND_LABEL_RE = re.compile(r"^[1-9]\d*(?:-[12])$")


_BARE_FINAL_LABEL_RE = re.compile(r"^[1-9]\d*$")


_SPLIT_PAIR_RE = re.compile(
    r"(?<!\d)([1-9]\d*)\s*[-—–]\s*1.{0,160}?\1\s*[-—–]\s*2(?!\d)"
)


_CPD_LETTER_PAIR_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:Cpd|Cmpd|Compound|化合物)\s*[-:]?\s*([1-9]\d{0,2})"
    r"(?![A-Za-z0-9-]).{0,120}?"
    r"(?:Cpd|Cmpd|Compound|化合物)\s*[-:]?\s*\1\s*A(?![A-Za-z0-9])",
    re.IGNORECASE,
)


_PRODUCT_VISIBLE_LABEL_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:examples?|cmpd|cpd|compound|实施例|化合物)\s*[-.:]?\s*([1-9]\d{0,2}[A-Z]?)(?![A-Za-z0-9-])",
    re.IGNORECASE,
)


_DIRECT_LABEL_RE = re.compile(
    r"(?<![A-Za-z0-9])([1-9]\d{0,2}[A-Z]?)(?![A-Za-z0-9-])", re.IGNORECASE
)


_ROUTE_STEP_LABEL_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:step|s)\s*[-.:]?\s*([1-9]\d{0,2})(?![A-Za-z0-9-])",
    re.IGNORECASE,
)


_RACEMIC_LABEL_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:rac|racemic)\s*[-.:]?\s*(?:cmpd|cpd|compound)?\s*[-.:]?\s*([1-9]\d{0,2}[A-Z]?)(?![A-Za-z0-9-])",
    re.IGNORECASE,
)


_VISIBLE_LABEL_SOURCE_RANK = {
    "page_strict": 0,
    "direct": 1,
    "page_wide": 2,
    "pdf_clip": 3,
}


_STRICT_VISIBLE_LABEL_SOURCES = {"page_strict", "direct", "pdf_clip"}


_VISUAL_LABEL_SOURCES = _STRICT_VISIBLE_LABEL_SOURCES | {"page_wide"}


_ROUTE_TITLE_RE = re.compile(
    r"(?:^|[\s\]\).;。；])(?:Examples?|Compounds?|实施例|化合物)\s*([1-9]\d{0,2}[A-Z]?)\s*[:：]",
    re.IGNORECASE,
)


def _is_intermediate(item: dict) -> bool:
    """判断一个化合物条目是否为 Intermediate（中间体）"""
    for key in ("prefix", "cpd_id", "cpd"):
        val = item.get(key, "")
        if val and _INTERMEDIATE_RE.match(str(val)):
            return True
    return False


def _filter_examples_only(items: list[dict]) -> list[dict]:
    """过滤掉 Intermediate，只保留 Example"""
    before = len(items)
    filtered = [item for item in items if not _is_intermediate(item)]
    removed = before - len(filtered)
    if removed > 0:
        logger.info(
            f"  [filter] 去除 {removed} 个 Intermediate，保留 {len(filtered)} 个 Example "
            f"(总共 {before})"
        )
    return filtered


def _page_text_for_page_no(
    pages_text: dict[int, str] | None, page_no: int, include_next: bool = False
) -> str:
    """Return OCR text for a 1-based PDF page without crossing to the next page by accident."""
    if not pages_text:
        return ""
    try:
        page_no_int = int(page_no)
    except (ValueError, TypeError, OverflowError):
        return ""
    keys = [page_no_int - 1]
    if include_next:
        keys.append(page_no_int)
    parts: list[str] = []
    for key in keys:
        text = str((pages_text or {}).get(key, "") or "")
        if text.strip():
            parts.append(text)
    return "\n".join(parts)


def _extract_chinese_compound_sequence(pages_text: dict[int, str]) -> list[int]:
    """Extract ordered "(化合物N)" identifiers from OCR text."""
    text = "\n".join(pages_text.get(i, "") for i in sorted(pages_text))
    nums = [int(n) for n in re.findall(r"化合\s*物\s*(\d+)", text)]
    # Keep OCR order but remove adjacent duplicates from repeated headers.
    ordered: list[int] = []
    for n in nums:
        if not ordered or ordered[-1] != n:
            ordered.append(n)
    return ordered


def _product_context_distance(
    pages_text: dict[int, str], page_no: int, compound_num: int
) -> int:
    fuzzy = _ocr_confusable_num_pattern(compound_num)
    fuzzy_token = rf"(?<![\dA-Za-z]){fuzzy}(?![\dA-Za-z-])"
    # For comma/range style product lists, the target number must itself be a
    # listed product token. Do not let "Examples 289-293 ... Int-12" satisfy
    # product context for Compound 12.
    list_fuzzy_token = rf"(?<![\dA-Za-z-]){fuzzy}(?![\dA-Za-z-])"
    compound_ref = (
        rf"(?:Compounds?|Cmpd|Cpd|化.?[合台]物)\s*[-:]?\s*"
        rf"(?:Cmpd|Cpd|Compound)?\s*[-:]?\s*{fuzzy_token}"
    )
    # Product context must point at an example or a compound identifier. A
    # broad "得到 ... 1" match also sees IUPAC locants in procedure text and
    # makes S1/S2 route annotations look like bare Compound 1/2 labels.
    heading_context = re.compile(
        rf"(?:Examples?|实施例)\s*{fuzzy_token}(?![\dA-Za-z-])"
        rf"|{compound_ref}\s*(?:[:：]|(?:的)?(?:preparation|synthesis|制备|合成))"
        rf"|(?:preparation|synthesis|制备|合成)[^\n]{{0,48}}{compound_ref}",
        re.IGNORECASE,
    )
    obtained_context = re.compile(
        rf"(?:得到|制备得到|分离制备得到)[^\n]{{0,80}}{compound_ref}",
        re.IGNORECASE,
    )

    # Chinese patents often combine enantiomer/product pairs in one heading:
    # "实施例51，52  化合物51、52的合成". Treat each listed number as product
    # context so the second product is not incorrectly blocked.
    pair_context = re.compile(
        rf"(?:Examples?|Compounds?|实施例|化.?[合台]物)[^\n]{{0,140}}"
        rf"(?<![\dA-Za-z])\d{{1,3}}(?![\dA-Za-z-])"
        rf"(?:[、,，/和及\s]+|\s+and\s+){list_fuzzy_token}",
        re.IGNORECASE,
    )

    best = 999
    for page_no_candidate in (
        page_no - 2,
        page_no - 1,
        page_no,
        page_no + 1,
        page_no + 2,
    ):
        key = page_no_candidate - 1
        text = str(pages_text.get(key, "") or "")
        if not text.strip():
            continue
        if page_no_candidate != page_no and compound_num <= 20:
            # Low labels are common in NMR text and route annotations. Do not
            # let a neighboring page's unrelated Example 139/246 etc. make a
            # bare "1" look like product context.
            continue
        if (
            heading_context.search(text)
            or obtained_context.search(text)
            or pair_context.search(text)
        ):
            best = min(best, abs(page_no_candidate - page_no))
    return best


def _page_has_product_context(
    pages_text: dict[int, str], page_no: int, compound_num: int
) -> bool:
    return _product_context_distance(pages_text, page_no, compound_num) < 999


def _line_estimated_y(line_idx: int) -> float:
    return float(line_idx) * 14.0


def _product_anchor_lines_from_text(
    text: str, active_bases: set[int]
) -> list[tuple[int, float, str]]:
    anchors: list[tuple[int, float, str]] = []
    colon_anchors: list[tuple[int, float, str]] = []
    if not text:
        return anchors
    seen: set[tuple[int, int]] = set()
    for line_idx, line in enumerate(str(text).splitlines()):
        clean = re.sub(r"\s+", " ", line).strip()
        if not clean or re.search(r"中间体", clean):
            continue
        compact = re.sub(r"\s+", "", clean)
        for num in active_bases:
            # Avoid running several OCR-fuzzy regexes for every active compound
            # on every long OCR line. Keep the cheap gate permissive for common
            # leading-5 confusions (51 -> S1/$1), but only evaluate likely hits.
            num_text = str(num)
            maybe_num = num_text in compact
            if not maybe_num and num_text.startswith("5") and len(num_text) > 1:
                maybe_num = any(
                    (lead + num_text[1:]) in compact for lead in ("S", "s", "$", "＄")
                )
            if not maybe_num:
                continue
            fuzzy = _ocr_confusable_num_pattern(num)
            fuzzy_token = rf"(?<![\dA-Za-z]){fuzzy}(?![\dA-Za-z-])"
            colon_match = re.search(
                rf"化.?[合台]物\s*{fuzzy_token}\s*[:：]", clean, re.IGNORECASE
            )
            context_patterns = [
                rf"化.?[合台]物\s*{fuzzy_token}\s*的制备",
                rf"(?:步骤\s*[\dS$]+\s*[:：]\s*)?(?:[A-Za-z]{{1,6}}\s*)?{fuzzy_token}\s*的制备",
                rf"得到(?:目标)?化.?[合台]物\s*{fuzzy_token}",
                rf"分离制备(?:分别)?得到化.?[合台]物[^\n]{{0,60}}{fuzzy_token}",
                rf"得到(?:目标)?\s*{fuzzy_token}\s*[（(]?\s*\d+(?:\.\d+)?\s*m?s?g",
            ]
            if colon_match or any(
                re.search(pat, clean, re.IGNORECASE) for pat in context_patterns
            ):
                key = (num, line_idx)
                if key in seen:
                    continue
                seen.add(key)
                anchor = (num, _line_estimated_y(line_idx), clean)
                anchors.append(anchor)
                if colon_match:
                    colon_anchors.append(anchor)

    def _dedupe_latest_per_compound(
        items: list[tuple[int, float, str]],
    ) -> list[tuple[int, float, str]]:
        latest: dict[int, tuple[int, float, str]] = {}
        for item in items:
            num, y0, _line = item
            if num not in latest or y0 >= latest[num][1]:
                latest[num] = item
        return sorted(latest.values(), key=lambda item: item[1])

    # If explicit "化合物 N:" analysis/product subsections are present, use
    # those as the only anchors on the page. Broader title/obtained lines can
    # mention several compounds at once and are too imprecise for structure
    # pairing; they caused final products to be shifted or stolen by neighbors.
    return _dedupe_latest_per_compound(colon_anchors or anchors)


def _int_or_default(value: Any, default: int = 999) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (ValueError, TypeError, OverflowError):
        return default


def _normalise_compound_label(text: str) -> str:
    text = text.strip()
    text = text.strip("()[]{}.,;:，。；：")
    text = text.replace("—", "-").replace("–", "-")
    if re.fullmatch(r"[1-9]\d*(?:-\d+)?[A-Z]?", text, re.IGNORECASE):
        text = text.upper()
    # NOTE: Do NOT auto-split "42" → "4-2". This caused many misbindings.
    # Only accept labels that already have hyphens (e.g. "1-1", "4-2").
    return text


def _cpd_sort_key(value: str):
    label = _normalise_compound_label(str(value or ""))
    parts = re.findall(r"\d+|\D+", label)
    return [int(part) if part.isdigit() else part.lower() for part in parts]


def _labels_from_ocr_texts(ocr_texts: list[str]) -> list[str]:
    labels: list[str] = []
    for text in ocr_texts or []:
        for value in _labels_from_ocr_text(str(text or "")):
            if value not in labels:
                labels.append(value)
    return labels


def _labels_from_ocr_text(text: str) -> list[str]:
    """Return visible product-label tokens while preserving route step guards."""
    raw_text = str(text or "")
    blocked_spans = [
        match.span(1)
        for pattern in (_ROUTE_STEP_LABEL_RE, _RACEMIC_LABEL_RE)
        for match in pattern.finditer(raw_text)
    ]
    protected_spans = [
        *blocked_spans,
        *[match.span(1) for match in _PRODUCT_VISIBLE_LABEL_RE.finditer(raw_text)],
    ]
    labels: list[str] = []
    for match in _PRODUCT_VISIBLE_LABEL_RE.finditer(raw_text):
        span = match.span(1)
        if any(
            span[0] < blocked[1] and blocked[0] < span[1] for blocked in blocked_spans
        ):
            continue
        value = match.group(1).upper()
        if value not in labels:
            labels.append(value)
    for match in _DIRECT_LABEL_RE.finditer(raw_text):
        span = match.span(1)
        if any(
            span[0] < protected[1] and protected[0] < span[1]
            for protected in protected_spans
        ):
            continue
        value = match.group(1).upper()
        if value not in labels:
            labels.append(value)
    return labels


def _nearby_ocr_label_kind(
    struct: dict,
    label_key: str,
    lines_by_page: dict[int, list[tuple[float, str]]] | None,
) -> str:
    """Classify a visual module's nearest OCR label as product or precursor."""
    if not label_key or not lines_by_page:
        return ""
    page_idx = int(struct.get("page_no") or 0) - 1
    y0 = float(struct.get("y0") or 0)
    y1 = float(struct.get("y1") or y0)
    best: tuple[float, str] | None = None
    label_pat = re.escape(label_key)
    for line_y, text in lines_by_page.get(page_idx, []):
        if not (y0 - 24 <= float(line_y) <= y1 + 28):
            continue
        compact = re.sub(r"\s+", "", str(text or ""))
        if re.search(
            rf"(?:Rac|Racemic)-?(?:Cmpd|Cpd|Compound)-?{label_pat}(?!\d)",
            compact,
            re.IGNORECASE,
        ):
            rank = (abs(float(line_y) - y1), "racemic")
        elif re.search(
            rf"(?:Cmpd|Cpd|Compound)-?{label_pat}(?!\d)", compact, re.IGNORECASE
        ):
            rank = (abs(float(line_y) - y1), "product")
        else:
            continue
        if best is None or rank[0] < best[0]:
            best = rank
    return best[1] if best else ""


def _nearby_exact_product_label(
    struct: dict,
    label_key: str,
    lines_by_page: dict[int, list[tuple[float, str]]] | None,
    row: list[dict] | None = None,
) -> str:
    """Return the nearest Cpd-style product label text for a structure."""
    if not label_key or not lines_by_page:
        return ""
    page_idx = int(struct.get("page_no") or 0) - 1
    y0 = float(struct.get("y0") or 0)
    y1 = float(struct.get("y1") or y0)
    labels: list[tuple[float, float, str]] = []
    for line_y, text in lines_by_page.get(page_idx, []):
        if not (y0 - 18 <= float(line_y) <= y1 + 40):
            continue
        value = str(text or "").strip()
        if _RACEMIC_LABEL_RE.search(value):
            continue
        for match in _PRODUCT_VISIBLE_LABEL_RE.finditer(value):
            label = match.group(1).upper()
            labels.append((abs(float(line_y) - y1), float(line_y), label))
    if not labels:
        return ""
    labels.sort(key=lambda item: (item[0], item[1]))
    nearest = labels[0]
    if nearest[2] != label_key and nearest[0] <= 42.0:
        return nearest[2]
    same_base = [
        item for item in labels if re.match(rf"^{re.escape(label_key)}[A-Z]?$", item[2])
    ]
    if not same_base:
        return ""
    same_base.sort(key=lambda item: (item[1], item[0]))
    if len(same_base) > 1:
        row_labels = [
            item[2] for item in same_base if abs(item[1] - same_base[0][1]) <= 3.0
        ]
        if len(row_labels) > 1 and row:
            row_labels = sorted(row_labels, key=lambda label: (len(label), label))
            # The OCR cache lacks x coordinates for these label lines. In
            # Chinese paired product rows the labels are printed left-to-right.
            # If a reaction row also contains unlabeled precursors, those are
            # typically to the left of the labeled final products.
            row_sorted = sorted(row, key=lambda item: float(item.get("x0") or 0))
            if len(row_sorted) > len(row_labels):
                row_sorted = row_sorted[-len(row_labels) :]
            sid = str(struct.get("id") or "")
            try:
                position = next(
                    idx
                    for idx, item in enumerate(row_sorted)
                    if str(item.get("id") or "") == sid
                )
            except StopIteration:
                position = -1
            if 0 <= position < len(row_labels):
                return row_labels[position]
            return ""
    return same_base[0][2]


def _passes_exact_visual_label_guard(
    struct: dict,
    label_key: str,
    lines_by_page: dict[int, list[tuple[float, str]]] | None,
    row: list[dict] | None = None,
) -> tuple[bool, str]:
    """Fail closed when nearby visible Cpd labels prove a suffix mismatch."""
    exact_label = _nearby_exact_product_label(struct, label_key, lines_by_page, row=row)
    if exact_label and exact_label != label_key:
        return False, exact_label
    return True, exact_label


def _split_pair_bases_from_text(text: str) -> list[int]:
    """Return split-product bases visible in OCR text, e.g. 7 from 7-1 ... 7-2."""
    bases: list[int] = []
    for m in _SPLIT_PAIR_RE.finditer(text.replace("\n", " ")):
        base = int(m.group(1))
        if base not in bases:
            bases.append(base)
    return bases


def _cpd_letter_pair_bases_from_text(text: str) -> list[int]:
    """Return bases from Cpd-N/Cpd-NA paired-product text."""
    bases: list[int] = []
    compact = re.sub(r"\s+", " ", str(text or ""))
    for match in _CPD_LETTER_PAIR_RE.finditer(compact):
        base = int(match.group(1))
        if base not in bases:
            bases.append(base)
    return bases


def _cpd_letter_pair_base_lines(
    page_no: int,
    page_text: str,
    ocr_line_map: dict[int, list[tuple[float, str]]] | None = None,
) -> list[tuple[int, float | None]]:
    """Return Cpd-N/Cpd-NA pair bases with approximate heading y coordinates."""
    lines = (ocr_line_map or {}).get(page_no - 1) or []
    found: list[tuple[int, float | None]] = []
    for idx, (y0, _text) in enumerate(lines):
        window = " ".join(text for _, text in lines[idx : idx + 3])
        if re.search(
            r"备注|相同|采用|参考|参照|same\s+route|same\s+procedure",
            window,
            re.IGNORECASE,
        ):
            continue
        for base in _cpd_letter_pair_bases_from_text(window):
            if base not in [item[0] for item in found]:
                found.append((base, y0))
    if found:
        return found
    return [(base, None) for base in _cpd_letter_pair_bases_from_text(page_text)]


def _cpd_letter_pair_label_y(
    base: int,
    page_no: int,
    lines_by_page: dict[int, list[tuple[float, str]]] | None,
) -> float | None:
    """Return y for the printed Cpd-N/Cpd-NA product-label row."""
    if not lines_by_page:
        return None
    base_text = str(base)
    left_label = rf"(?:Cpd|Cmpd|Compound)\s*[-:]?\s*{re.escape(base_text)}(?:NH)?(?![A-Za-z0-9-])"
    right_label = (
        rf"(?:Cpd|Cmpd|Compound)\s*[-:]?\s*{re.escape(base_text)}\s*A(?![A-Za-z0-9])"
    )
    label_re = re.compile(
        rf"{left_label}.{{0,80}}?"
        rf"(?:Cpd|Cmpd|Compound)\s*[-:]?\s*{re.escape(base_text)}\s*A(?![A-Za-z0-9])",
        re.IGNORECASE,
    )
    single_left_re = re.compile(left_label, re.IGNORECASE)
    single_right_re = re.compile(right_label, re.IGNORECASE)
    lines = lines_by_page.get(page_no - 1) or []
    for idx, (y0, text) in enumerate(lines):
        window = " ".join(str(item[1] or "") for item in lines[idx : idx + 2])
        if re.search(
            r"实施例|Example|制备|备注|相同|采用|参考|参照|same\s+route|same\s+procedure",
            window,
            re.IGNORECASE,
        ):
            continue
        if len(window) > 140:
            continue
        if label_re.search(window) or (
            single_left_re.search(window) and single_right_re.search(window)
        ):
            return float(y0)
        line_text = str(text or "")
        if not single_left_re.search(line_text):
            continue
        nearby_texts: list[str] = []
        for other_y, other_text in lines[idx : idx + 6]:
            if abs(float(other_y) - float(y0)) > 24.0:
                break
            value = str(other_text or "")
            if re.search(
                r"实施例|Example|制备|备注|相同|采用|参考|参照|same\s+route|same\s+procedure",
                value,
                re.IGNORECASE,
            ):
                continue
            nearby_texts.append(value)
        nearby_window = " ".join(nearby_texts)
        if len(nearby_window) <= 160 and single_right_re.search(nearby_window):
            return float(y0)
    return None


def _binding_base_num(binding: dict) -> int | None:
    """Return the parent compound number for de-duplicating mixed bind rules."""
    return _base_cpd_num(binding.get("compound_id") or binding.get("cpd") or "")


def _cpd_label_key(value: str) -> str:
    return printed_identifier_key(value)


def _binding_label_key(binding: dict) -> str:
    return _cpd_label_key(
        binding.get("compound_id")
        or binding.get("cpd")
        or binding.get("visible_label")
        or ""
    )


def _active_label_keys(active_cpds: list[str] | None) -> set[str]:
    return {key for key in (_cpd_label_key(cpd) for cpd in (active_cpds or [])) if key}


def _visible_label_keys_for_binding(binding: dict) -> set[str]:
    keys: set[str] = set()
    if binding.get("visible_label"):
        key = _cpd_label_key(str(binding.get("visible_label") or ""))
        if key:
            keys.add(key)
    for label in binding.get("visible_labels") or []:
        key = _cpd_label_key(str(label or ""))
        if key:
            keys.add(key)
    return keys


def _strict_visible_label_keys_for_binding(binding: dict) -> set[str]:
    keys: set[str] = set()
    for candidate in binding.get("visible_label_candidates") or []:
        source = str(candidate.get("source") or "")
        if source not in _STRICT_VISIBLE_LABEL_SOURCES:
            continue
        key = _cpd_label_key(str(candidate.get("label") or ""))
        if key:
            keys.add(key)
    if (
        not keys
        and binding.get("visible_label_crop_source") in _STRICT_VISIBLE_LABEL_SOURCES
    ):
        key = _cpd_label_key(str(binding.get("visible_label") or ""))
        if key:
            keys.add(key)
    return keys


def _visual_label_keys_for_binding(
    binding: dict,
    *,
    include_wide: bool = True,
) -> set[str]:
    allowed_sources = (
        _VISUAL_LABEL_SOURCES if include_wide else _STRICT_VISIBLE_LABEL_SOURCES
    )
    keys: set[str] = set()
    for candidate in binding.get("visible_label_candidates") or []:
        source = str(candidate.get("source") or "")
        if source not in allowed_sources:
            continue
        key = _cpd_label_key(str(candidate.get("label") or ""))
        if key:
            keys.add(key)
    source = str(binding.get("visible_label_crop_source") or "")
    if source in allowed_sources:
        key = _cpd_label_key(str(binding.get("visible_label") or ""))
        if key:
            keys.add(key)
    return keys


def _is_truncated_visible_prefix(target_key: str, visible_key: str) -> bool:
    if not target_key or not visible_key:
        return False
    if not re.fullmatch(r"\d{3}[A-Z]?", target_key) or not re.fullmatch(
        r"\d{1,2}[A-Z]?", visible_key
    ):
        return False
    return target_key.startswith(visible_key)


def _is_short_internal_visible_key(target_key: str, visible_key: str) -> bool:
    """Return True for atom/reagent/NMR-like labels inside a stronger binding."""
    if not target_key or not visible_key or target_key == visible_key:
        return False
    if not re.fullmatch(r"\d{2,3}[A-Z]?", target_key):
        return False
    if not re.fullmatch(r"\d{1,2}[A-Z]?", visible_key):
        return False
    match = re.match(r"\d+", visible_key)
    if not match:
        return False
    value = int(match.group(0))
    # Only a lone "1" is routinely an internal stereochemical/route annotation.
    # Larger visible numbers such as 2/4/10 may be real competing products or
    # intermediates, so derived crops must fail closed instead of auto-confirming.
    return value == 1 or _is_truncated_visible_prefix(target_key, visible_key)


def _route_title_numbers_from_text(
    page_text: str, active_keys: set[str] | None = None
) -> list[str]:
    labels: list[str] = []
    for match in _ROUTE_TITLE_RE.finditer(str(page_text or "")):
        key = _cpd_label_key(match.group(1))
        if not key:
            continue
        if active_keys and key not in active_keys:
            continue
        if key not in labels:
            labels.append(key)
    return labels


def _labels_near_structure(words: list[dict], struct: dict) -> list[str]:
    x0, x1 = float(struct["x0"]), float(struct.get("x1", struct["x0"]))
    y1 = float(struct.get("y1", struct["y0"]))
    cx = (x0 + x1) / 2
    width = max(25.0, x1 - x0)
    labels: list[str] = []
    for word in words:
        label = _normalise_compound_label(word["text"])
        dx = abs(float(word["x"]) - cx)
        y = float(word["y"])
        near = dx <= max(width * 0.6, 40.0) and y1 - 10 <= y <= y1 + 65
        if near and label:
            labels.append(label)
    return labels


def _base_cpd_num(value: str) -> int | None:
    m = re.search(r"(\d+)", str(value or ""))
    return int(m.group(1)) if m else None


def _ocr_confusable_num_pattern(num: int | str) -> str:
    """Build a narrow pattern for OCR-confused compound numbers.

    This is meant for Chinese heading/product contexts only. A leading 5 is
    commonly read as S/s/$, and 1/2 can be read as l/I/z in scanned patents.
    """
    pieces: list[str] = []
    for ch in str(num):
        if ch == "5":
            pieces.append(r"[5S＄$s]")
        elif ch == "1":
            pieces.append(r"[1lI]")
        elif ch == "2":
            pieces.append(r"[2zZ]")
        else:
            pieces.append(re.escape(ch))
    return r"\s*".join(pieces)
