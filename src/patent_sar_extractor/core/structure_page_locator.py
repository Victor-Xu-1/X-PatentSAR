"""
Deterministically locate likely structure pages for active compounds.

This module is intentionally deterministic. It does not open a second main
pipeline; it narrows the structure search space using activity-derived targets.
"""

from __future__ import annotations

import logging
import re
from functools import lru_cache
from pathlib import Path

from patent_sar_extractor.contracts import (
    STRUCTURE_LOCATION_SCHEMA,
    STRUCTURE_LOCATION_SCHEMA_VERSION,
    artifact_identity,
)
from patent_sar_extractor.artifact_io import write_json_atomic
from patent_sar_extractor.core.page_ocr_cache import build_page_ocr_cache, load_page_ocr_cache, save_page_ocr_cache

logger = logging.getLogger(__name__)

STRUCTURE_SIGNAL_RE = re.compile(
    r"实施例\s*\d+|化合物\s*\d+|Example\s+\d+|Compound\s+\d+|Cpd[-\s]?\d+|"
    r"制备例|合成例|Synthesis|Preparation|MS\s*m/z|NMR|LCMS|LC-MS|HPLC|"
    r"收率|产率|反应|得到|mmol|mL|mg|°C|chemical\s+formula|formula\s+shown|"
    r"formula\s+of\s+the\s+new\s+compound|claimed\s+compound",
    re.IGNORECASE,
)
STRUCTURE_TABLE_HEADER_RE = re.compile(
    r"化合物编号|化合物\s*(?:结构|列表)|结构式|化学结构|结构列表|结构表|"
    r"\bcompounds?\s+(?:table|list)\b|"
    r"\b(?:compound|cmpd)\s*(?:no\.?|number|id|#)\b|"
    r"\b(?:compound|cmpd).{0,32}\b(?:structure|formula)\b|"
    r"\b(?:structure|formula).{0,32}\b(?:compound|cmpd)\b",
    re.IGNORECASE,
)
STRUCTURE_TABLE_ROW_ID_RE = re.compile(r"(?:^|\n)\s*\d{1,4}(?=\s|$)")
STRUCTURE_TABLE_MASS_RE = re.compile(r"\b\d{3}\.\d\b")
STRUCTURE_TABLE_FLATTENED_ID_MASS_RE = re.compile(
    r"(?<![\dA-Za-z.-])\d{1,4}(?![\dA-Za-z.-])(?=.{0,240}?\b\d{3}\.\d\b)",
    re.DOTALL,
)
STRUCTURE_TABLE_CHEM_NAME_RE = re.compile(
    r"哌啶|吡啶|苯基|噻吩|呋喃|二酮|恶唑|噻唑|"
    r"phenyl|pyrid|thien|furyl|piperid|dione|oxazol|thiazol",
    re.IGNORECASE,
)
STRUCTURE_TABLE_SERIES_ID_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:[A-Z]|[1Il])\s*[-–—]\s*\d{1,5}(?!\d)",
    re.IGNORECASE,
)
STRUCTURE_PROSE_ASSAY_RE = re.compile(
    r"\bSynthesized\s+in\b|\bHNMR\b|\bNMR\b|\bMS\s*\(\s*ESI|\bm/z\b|"
    r"\bIC50\b|\bEC50\b|\bDC50\b|\bDmax\b|\bNanoBiT\b|\bHTRF\b",
    re.IGNORECASE,
)


def _normalize_cpd_label(value: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return ""
    match = re.search(
        r"(?:compound|cpd|example|实施例|化合物)\s*[-:]?\s*(\d+(?:-\d+)?[A-Z]?)",
        text,
        re.IGNORECASE,
    )
    if match:
        return f"Compound {match.group(1).upper()}"
    bare = re.fullmatch(r"(\d+(?:-\d+)?[A-Z]?)", text, re.IGNORECASE)
    if bare:
        return f"Compound {bare.group(1).upper()}"
    return text


def _is_singleton_main_compound_label(value: str) -> bool:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return bool(re.search(
        r"^(?:claim\s*1\s+compound|claimed\s+compound|main\s+compound|single(?:ton)?\s+compound)$",
        text,
        re.IGNORECASE,
    ))


def _singleton_structure_patterns() -> list[re.Pattern]:
    patterns = [
        r"claim\s*1.{0,180}(?:formula\s+shown\s+here|shown\s+here|new\s+compound)",
        r"(?:formula\s+shown\s+here|shown\s+here).{0,180}claim\s*1",
        r"chemical\s+formula.{0,160}(?:Figure\s*1|Figure\s*2|new\s+compound)",
        r"formula\s+of\s+the\s+new\s+compound",
        r"new\s+compound\s+with\s+the\s+chemical\s+name",
    ]
    return [re.compile(pattern, re.IGNORECASE | re.DOTALL) for pattern in patterns]


@lru_cache(maxsize=2048)
def _cpd_patterns(cpd: str) -> list[re.Pattern]:
    norm = _normalize_cpd_label(cpd)
    if _is_singleton_main_compound_label(norm):
        return _singleton_structure_patterns()
    m = re.search(r"Compound\s+(\d+(?:-\d+)?[A-Z]?)", norm, re.IGNORECASE)
    if not m:
        return []
    num = re.escape(m.group(1))
    boundary = r"(?![\dA-Za-z-])"
    patterns = [
        rf"Compound\s*{num}{boundary}",
        rf"Cpd[-\s]?{num}{boundary}",
        rf"化合物\s*{num}{boundary}",
        rf"实施例\s*{num}{boundary}",
        rf"Example\s*{num}{boundary}",
    ]
    return [re.compile(p, re.IGNORECASE) for p in patterns]


def _ocr_confusable_num_pattern(num: str) -> str:
    """Return a conservative OCR-tolerant pattern for compound IDs.

    Chinese scanned patents often turn a leading 5 into S/s/$ in headings
    such as "实施例 S1" or "化合物 $2". Only use this in compound-heading
    contexts, never as a free-standing token search.
    """
    pieces = []
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


def _cpd_ocr_confusable_patterns(cpd: str) -> list[re.Pattern]:
    norm = _normalize_cpd_label(cpd)
    m = re.search(r"Compound\s+(\d+)(?:-\d+)?", norm, re.IGNORECASE)
    if not m:
        return []
    num = m.group(1)
    if "5" not in num:
        return []
    fuzzy = _ocr_confusable_num_pattern(num)
    patterns = [
        rf"(?:实施例|化合物)\s*{fuzzy}(?![\dA-Za-z-])",
        rf"(?:得到|制备得到|分离制备得到)[^。\n]{{0,40}}(?:化合物)\s*{fuzzy}(?![\dA-Za-z-])",
    ]
    return [re.compile(p, re.IGNORECASE) for p in patterns]


@lru_cache(maxsize=2048)
def _cpd_table_row_pattern(cpd: str) -> re.Pattern | None:
    norm = _normalize_cpd_label(cpd)
    m = re.search(r"Compound\s+(\d+(?:-\d+)?[A-Z]?)", norm, re.IGNORECASE)
    if not m:
        return None
    raw_num = m.group(1)
    num = re.escape(raw_num)
    patterns = [
        rf"(?:^|\n)\s*{num}(?=\s|$)(?![A-Za-z-])",
        # Dedicated patent structure tables frequently use a series label
        # such as I-123. OCR often confuses the leading I with 1 or l.
        rf"(?<![A-Za-z0-9])(?:[A-Z]|[1Il])\s*[-–—]\s*{num}(?!\d)",
    ]
    if len(raw_num) >= 2:
        # OCR from ruled structure tables is often flattened into one paragraph.
        # Require a nearby LC-MS-like mass so internal chemical locants do not
        # become compound-row hits.
        patterns.append(rf"(?<![\dA-Za-z.-]){num}(?![\dA-Za-z.-])(?=.{{0,240}}\b\d{{3}}\.\d\b)")
    return re.compile("|".join(patterns), re.IGNORECASE | re.DOTALL)


@lru_cache(maxsize=512)
def _is_structure_table_page(text: str) -> bool:
    value = str(text or "")
    if not value.strip():
        return False
    if STRUCTURE_TABLE_HEADER_RE.search(value):
        return True
    row_ids = len(STRUCTURE_TABLE_ROW_ID_RE.findall(value))
    masses = len(STRUCTURE_TABLE_MASS_RE.findall(value))
    numbered_compounds = len(re.findall(r"化合物\s*\d+", value, re.IGNORECASE))
    english_compounds = len(re.findall(r"\bCompound\s*\d+\b", value, re.IGNORECASE))
    flattened_id_mass_hits = len(STRUCTURE_TABLE_FLATTENED_ID_MASS_RE.findall(value))
    chem_name_hits = len(STRUCTURE_TABLE_CHEM_NAME_RE.findall(value))
    series_id_hits = len(STRUCTURE_TABLE_SERIES_ID_RE.findall(value))
    compact_length = len(re.sub(r"\s+", "", value))
    explicit_series_header = bool(re.search(
        r"(?:[A-Z]|[1Il])\s*-\s*#.{0,48}\bStructure\b|"
        r"\bTable\s*\d+\s*[.:]?\s*(?:Exemplary\s+)?Compounds?\b",
        value,
        re.IGNORECASE | re.DOTALL,
    ))
    sparse_series_continuation = (
        (series_id_hits >= 2 and compact_length <= 500)
        or (series_id_hits == 1 and compact_length <= 100)
    )
    dense_english_grid = english_compounds >= 6 and not STRUCTURE_PROSE_ASSAY_RE.search(value)
    dense_numbered_list = row_ids >= 8 and not STRUCTURE_PROSE_ASSAY_RE.search(value)
    dense_flattened_grid = (
        flattened_id_mass_hits >= 3
        and masses >= 3
        and chem_name_hits >= 2
        and not STRUCTURE_PROSE_ASSAY_RE.search(value)
    )
    return (
        (row_ids >= 3 and masses >= 3)
        or (numbered_compounds >= 2 and masses >= 2)
        or dense_english_grid
        or dense_numbered_list
        or dense_flattened_grid
        or explicit_series_header
        or sparse_series_continuation
    )


def _expand_structure_table_block(seed_pages: set[int], available_pages: list[int], page_text_lookup: dict[int, str]) -> set[int]:
    if not seed_pages:
        return set()
    available_set = set(available_pages)
    expanded = set(seed_pages)
    frontier = list(sorted(seed_pages))
    while frontier:
        page_idx = frontier.pop()
        for neighbor in (page_idx - 1, page_idx + 1):
            if neighbor not in available_set or neighbor in expanded:
                continue
            if _is_structure_table_page(page_text_lookup.get(neighbor, "")):
                expanded.add(neighbor)
                frontier.append(neighbor)
    return expanded


def _contiguous_page_blocks(pages: set[int]) -> list[list[int]]:
    blocks: list[list[int]] = []
    for page_idx in sorted(pages):
        if not blocks or page_idx != blocks[-1][-1] + 1:
            blocks.append([page_idx])
        else:
            blocks[-1].append(page_idx)
    return blocks


def _explicit_table_row_ids(text: str) -> set[str]:
    """Read punctuated ID cells only under an explicit structure-table header.

    Ordinary numbered Tables A/B/C are not I-series tables. Decimal masses,
    chemical locants and prose enumeration must not become row evidence.
    """
    if not STRUCTURE_TABLE_HEADER_RE.search(text):
        return set()
    return {
        match.group(1).upper()
        for match in re.finditer(r"(?<![\w.])([1-9]\d{0,3}[A-Z]?)\.(?=\s|$)", text, re.I)
    }


def _has_table_row_evidence(text: str) -> bool:
    return bool(STRUCTURE_TABLE_SERIES_ID_RE.search(text) or _explicit_table_row_ids(text))


def _covered_active_cpds(pages: list[int], page_text_lookup: dict[int, str], active_cpds: list[str]) -> dict[str, list[int]]:
    matched: dict[str, list[int]] = {}
    printed_ids = {page: _explicit_table_row_ids(page_text_lookup.get(page, "")) for page in pages}
    for raw_cpd in active_cpds:
        cpd = _normalize_cpd_label(raw_cpd)
        if not cpd:
            continue
        patterns = _cpd_patterns(cpd)
        table_row_pattern = _cpd_table_row_pattern(cpd)
        label = cpd.removeprefix("Compound ")
        hits = [
            page_idx for page_idx in pages
            if (
                label in printed_ids[page_idx]
                or any(pattern.search(page_text_lookup.get(page_idx, "")) for pattern in patterns)
                or (
                    table_row_pattern is not None
                    and table_row_pattern.search(page_text_lookup.get(page_idx, ""))
                )
            )
        ]
        if hits:
            matched[cpd] = hits
    return matched


def locate_structure_pages(
    pdf_path: str,
    classification: dict,
    active_cpds: list[str],
    output_path: str = "",
    workers: int = 1,
    ocr_cache_path: str = "",
) -> dict:
    """
    Return a compact, activity-led list of candidate structure pages.

    Strategy:
    - Search only synthesis/candidate pages.
    - Prefer pages that mention active compound IDs and look like experimental pages.
    - Expand one page around direct hits to avoid clipping nearby structure figures.
    """
    synthesis_pages = classification.get("synthesis_pages", []) or []
    candidate_pages = classification.get("candidate_pages", []) or []
    activity_pages = set(classification.get("activity_pages", []) or [])
    singleton_mode = any(_is_singleton_main_compound_label(cpd) for cpd in (active_cpds or []))
    candidate_pool = sorted(set(synthesis_pages or candidate_pages))
    if not candidate_pool:
        candidate_pool = sorted(set(candidate_pages))

    if not candidate_pool:
        payload = {
            **artifact_identity(STRUCTURE_LOCATION_SCHEMA, STRUCTURE_LOCATION_SCHEMA_VERSION),
            "candidate_pool": [],
            "selected_pages": [],
            "matched_cpds": {},
            "unmatched_cpds": [_normalize_cpd_label(c) for c in active_cpds],
            "reason": "no_candidate_pool",
        }
        if output_path:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            write_json_atomic(output_path, payload)
        return payload

    shared_cache = load_page_ocr_cache(ocr_cache_path) if ocr_cache_path else {"page_texts": {}, "ocr_line_map": {}}
    missing = [idx for idx in candidate_pool if str(idx) not in shared_cache.get("page_texts", {})]
    if missing:
        built = build_page_ocr_cache(pdf_path, missing, workers=workers, min_native_chars=40)
        shared_cache["page_texts"].update(built.get("page_texts", {}))
        shared_cache["ocr_line_map"].update(built.get("ocr_line_map", {}))

    # Accuracy-first rule: if the patent contains a dedicated compound
    # structure table/list, it is the authoritative source even when the page
    # classifier did not call those pages synthesis pages. Scan all non-activity
    # candidate pages once and reuse the shared OCR cache for every later module.
    structure_scan_pool = sorted(set(candidate_pages or candidate_pool) - activity_pages)
    scan_missing = [
        idx for idx in structure_scan_pool
        if str(idx) not in shared_cache.get("page_texts", {})
    ]
    cache_updated = bool(missing)
    if scan_missing:
        built = build_page_ocr_cache(pdf_path, scan_missing, workers=workers, min_native_chars=40)
        shared_cache["page_texts"].update(built.get("page_texts", {}))
        shared_cache["ocr_line_map"].update(built.get("ocr_line_map", {}))
        cache_updated = True
    if ocr_cache_path and cache_updated:
        save_page_ocr_cache(ocr_cache_path, shared_cache)

    page_texts = {
        idx: str(shared_cache.get("page_texts", {}).get(str(idx), ""))
        for idx in candidate_pool
    }
    ocr_line_map = {
        idx: shared_cache.get("ocr_line_map", {}).get(str(idx), [])
        for idx in candidate_pool
        if shared_cache.get("ocr_line_map", {}).get(str(idx))
    }

    all_cached_pages = sorted(
        int(key)
        for key, value in shared_cache.get("page_texts", {}).items()
        if str(value).strip()
    )
    if singleton_mode:
        singleton_pages = [
            idx for idx in all_cached_pages
            if idx not in activity_pages
            and any(pattern.search(str(shared_cache.get("page_texts", {}).get(str(idx), ""))) for pattern in _singleton_structure_patterns())
        ]
        if singleton_pages:
            candidate_pool = sorted(set(candidate_pool) | set(singleton_pages))
            for idx in singleton_pages:
                page_texts.setdefault(idx, str(shared_cache.get("page_texts", {}).get(str(idx), "")))
                lines = shared_cache.get("ocr_line_map", {}).get(str(idx), [])
                if lines:
                    ocr_line_map.setdefault(idx, lines)

    expanded_pool = [
        idx
        for idx in all_cached_pages
        if idx not in activity_pages and STRUCTURE_SIGNAL_RE.search(str(shared_cache.get("page_texts", {}).get(str(idx), "")))
    ]
    expanded_text_lookup = {
        idx: str(shared_cache.get("page_texts", {}).get(str(idx), ""))
        for idx in expanded_pool
    }
    table_text_lookup = {
        idx: str(shared_cache.get("page_texts", {}).get(str(idx), ""))
        for idx in all_cached_pages
        if idx not in activity_pages
    }
    detected_structure_table_pages = {
        idx for idx, text in table_text_lookup.items()
        if _is_structure_table_page(text)
    }
    table_blocks = _contiguous_page_blocks(detected_structure_table_pages)
    table_block_matches = [
        (block, _covered_active_cpds(block, table_text_lookup, active_cpds))
        for block in table_blocks
    ]
    authoritative_table_pages: list[int] = []
    authoritative_table_matches: dict[str, list[int]] = {}
    if table_block_matches:
        authoritative_table_pages, authoritative_table_matches = max(
            table_block_matches,
            key=lambda item: (len(item[1]), len(item[0])),
        )
        # Generic formula prose immediately after a structure table may satisfy
        # broad table heuristics.  Trim only the block edges that contain no
        # series-number rows; never remove an interior continuation page.
        authoritative_table_pages = list(authoritative_table_pages)
        while authoritative_table_pages and not _has_table_row_evidence(
            table_text_lookup.get(authoritative_table_pages[-1], "")
        ):
            authoritative_table_pages.pop()
        while authoritative_table_pages and not _has_table_row_evidence(
            table_text_lookup.get(authoritative_table_pages[0], "")
        ):
            authoritative_table_pages.pop(0)
        authoritative_table_matches = _covered_active_cpds(
            authoritative_table_pages,
            table_text_lookup,
            active_cpds,
        )
        if len(authoritative_table_matches) < 6:
            authoritative_table_pages = []
            authoritative_table_matches = {}

    matched_cpds: dict[str, list[int]] = dict(authoritative_table_matches)
    # A dedicated structures table is the patent's authoritative compound-to-image
    # source. Only unresolved active IDs fall back to synthesis/prose pages.
    selected = set(authoritative_table_pages)

    for raw_cpd in active_cpds:
        cpd = _normalize_cpd_label(raw_cpd)
        if not cpd:
            continue
        if cpd in matched_cpds:
            continue
        patterns = _cpd_patterns(cpd)
        table_row_pattern = _cpd_table_row_pattern(cpd)
        hits = []
        for page_idx in candidate_pool:
            text = page_texts.get(page_idx, "")
            if not text:
                continue
            if any(p.search(text) for p in patterns):
                if STRUCTURE_SIGNAL_RE.search(text):
                    hits.append(page_idx)
            elif table_row_pattern and _is_structure_table_page(text) and table_row_pattern.search(text):
                hits.append(page_idx)
        if not hits:
            for page_idx in candidate_pool:
                text = page_texts.get(page_idx, "")
                if text and (
                    any(p.search(text) for p in patterns)
                    or any(p.search(text) for p in _cpd_ocr_confusable_patterns(cpd))
                    or (table_row_pattern and _is_structure_table_page(text) and table_row_pattern.search(text))
                ):
                    hits.append(page_idx)
        if hits:
            matched_cpds[cpd] = sorted(set(hits))
            for hit in hits:
                selected.add(hit)
                if hit - 1 in candidate_pool:
                    selected.add(hit - 1)
                if hit + 1 in candidate_pool:
                    selected.add(hit + 1)
            table_block = _expand_structure_table_block(set(hits), candidate_pool, page_texts)
            selected.update(table_block)

    for raw_cpd in active_cpds:
        cpd = _normalize_cpd_label(raw_cpd)
        if not cpd or cpd in matched_cpds:
            continue
        patterns = _cpd_patterns(cpd)
        table_row_pattern = _cpd_table_row_pattern(cpd)
        hits = []
        for page_idx in expanded_pool:
            text = str(shared_cache.get("page_texts", {}).get(str(page_idx), ""))
            if text and (
                any(p.search(text) for p in patterns)
                or any(p.search(text) for p in _cpd_ocr_confusable_patterns(cpd))
                or (table_row_pattern and _is_structure_table_page(text) and table_row_pattern.search(text))
            ):
                hits.append(page_idx)
        if hits:
            matched_cpds[cpd] = sorted(set(hits))
            for hit in hits:
                selected.add(hit)
                if hit - 1 in expanded_pool:
                    selected.add(hit - 1)
                if hit + 1 in expanded_pool:
                    selected.add(hit + 1)
            table_block = _expand_structure_table_block(set(hits), expanded_pool, expanded_text_lookup)
            selected.update(table_block)

    if not selected:
        selected = set(candidate_pool)
        reason = "no_exact_cpd_hits_using_synthesis_pool"
    else:
        reason = "structure_table_priority_with_activity_fallback" if authoritative_table_pages else "activity_led_cpd_hits"
        if not authoritative_table_pages and any(page not in candidate_pool for page in selected):
            reason = "activity_led_cpd_hits_with_expanded_scan"

    active_norm = {cpd for cpd in (_normalize_cpd_label(raw) for raw in active_cpds) if cpd}
    table_covered_norm = set(authoritative_table_matches)
    table_covers_all_active = bool(authoritative_table_pages) and bool(active_norm) and active_norm.issubset(table_covered_norm)
    unmatched_norm = sorted(cpd for cpd in active_norm if cpd not in matched_cpds)
    unmatched_ratio = len(unmatched_norm) / max(len(active_norm), 1)
    broad_activity_table = len(active_cpds) >= 100 and unmatched_ratio >= 0.30
    if broad_activity_table and not authoritative_table_pages:
        # Large biology tables often list hundreds of active examples, while the
        # synthesis section may describe many of them in structure tables whose
        # OCR text does not repeat every active ID. In that case, exact text hits
        # are too narrow and silently drop structures. Prefer full synthesis/core
        # coverage and disable focus crops so downstream visual labels can bind
        # every available structure.
        selected = set(candidate_pool)
        reason = "broad_activity_table_full_synthesis_scan"
    elif table_covers_all_active and not unmatched_norm:
        reason = "structure_table_authoritative_complete"
    elif broad_activity_table and authoritative_table_pages:
        # Once a real structure table exists it stays authoritative. Do not
        # replace table-backed rows with a broad synthesis-page scan merely
        # because OCR left some active labels unresolved.
        reason = "structure_table_priority_with_unresolved_review"

    crop_regions = {}
    if not broad_activity_table:
        for page_idx in sorted(selected):
            lines = ocr_line_map.get(page_idx, []) or []
            if not lines:
                continue
            matched_y = []
            for raw_cpd, hits in matched_cpds.items():
                if page_idx not in hits:
                    continue
                patterns = _cpd_patterns(raw_cpd)
                for line in lines:
                    text = str(line.get("text", ""))
                    if any(p.search(text) for p in patterns):
                        matched_y.append(float(line.get("y0", 0)))
            if not matched_y:
                continue
            # Accuracy first: synthesis pages often place the authoritative
            # final product drawing above the paragraph/title that mentions the
            # active compound. Cropping from the text hit downward can silently
            # remove the page-top final structure and leave only route
            # intermediates. Keep the full vertical chemistry band for selected
            # active-led pages; downstream visual-label binding and activity
            # gating remove non-active/intermediate structures.
            top = 0.0
            bottom = 790.0
            crop_regions[str(page_idx)] = {
                "x0": 20,
                "x1": 575,
                "y0": round(top, 1),
                "y1": round(bottom, 1),
                "source": "activity_led_locator",
            }

    payload = {
        **artifact_identity(STRUCTURE_LOCATION_SCHEMA, STRUCTURE_LOCATION_SCHEMA_VERSION),
        "candidate_pool": candidate_pool,
        "expanded_pool": expanded_pool,
        "selected_pages": sorted(selected),
        "structure_table_pages": authoritative_table_pages,
        "detected_structure_table_pages": sorted(detected_structure_table_pages),
        "structure_table_covered_cpds": sorted(authoritative_table_matches),
        "structure_table_priority": bool(authoritative_table_pages),
        "structure_table_coverage_count": len(authoritative_table_matches),
        "matched_cpds": matched_cpds,
        "ocr_text_map": {str(k): v for k, v in page_texts.items() if v},
        "ocr_line_map": {str(k): v for k, v in ocr_line_map.items() if v},
        "crop_regions": crop_regions,
        "unmatched_cpds": unmatched_norm,
        "reason": reason,
        "broad_activity_table": broad_activity_table,
        "unmatched_ratio": round(unmatched_ratio, 4),
    }
    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        write_json_atomic(output_path, payload)
    logger.info("Structure page locator selected %s/%s candidate pages", len(payload["selected_pages"]), len(candidate_pool))
    return payload
