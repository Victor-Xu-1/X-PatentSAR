"""Locate all evidenced structures; activity labels never gate page coverage."""

from __future__ import annotations

import logging
import re
from functools import lru_cache
from pathlib import Path

from patent_sar_extractor.artifact_io import write_json_atomic
from patent_sar_extractor.contracts import (
    STRUCTURE_LOCATION_SCHEMA,
    STRUCTURE_LOCATION_SCHEMA_VERSION,
    artifact_identity,
)
from patent_sar_extractor.core.page_ocr_cache import (
    build_page_ocr_cache,
    load_page_ocr_cache,
    save_page_ocr_cache,
)
from patent_sar_extractor.core.structure_page_evidence import (
    _explicit_table_row_ids,
    _has_table_row_evidence,
    structure_page_evidence,
)

logger = logging.getLogger(__name__)
STRUCTURE_COVERAGE_POLICY = "all_evidence_backed_structures"


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
    return f"Compound {bare.group(1).upper()}" if bare else text


def _is_singleton_main_compound_label(value: str) -> bool:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return bool(
        re.search(
            r"^(?:claim\s*1\s+compound|claimed\s+compound|main\s+compound|single(?:ton)?\s+compound)$",
            text,
            re.IGNORECASE,
        )
    )


def _singleton_structure_patterns() -> list[re.Pattern]:
    return [
        re.compile(pattern, re.IGNORECASE | re.DOTALL)
        for pattern in (
            r"claim\s*1.{0,180}(?:formula\s+shown\s+here|shown\s+here|new\s+compound)",
            r"(?:formula\s+shown\s+here|shown\s+here).{0,180}claim\s*1",
            r"chemical\s+formula.{0,160}(?:Figure\s*1|Figure\s*2|new\s+compound)",
            r"formula\s+of\s+the\s+new\s+compound",
            r"new\s+compound\s+with\s+the\s+chemical\s+name",
        )
    ]


@lru_cache(maxsize=2048)
def _cpd_patterns(cpd: str) -> list[re.Pattern]:
    norm = _normalize_cpd_label(cpd)
    if _is_singleton_main_compound_label(norm):
        return _singleton_structure_patterns()
    match = re.search(r"Compound\s+(\d+(?:-\d+)?[A-Z]?)", norm, re.IGNORECASE)
    if not match:
        return []
    number = re.escape(match.group(1))
    return [
        re.compile(pattern, re.IGNORECASE)
        for pattern in (
            rf"Compound\s*{number}(?![\dA-Za-z-])",
            rf"Cpd[-\s]?{number}(?![\dA-Za-z-])",
            rf"化合物\s*{number}(?![\dA-Za-z-])",
            rf"实施例\s*{number}(?![\dA-Za-z-])",
            rf"Example\s*{number}(?![\dA-Za-z-])",
        )
    ]


def _ocr_confusable_num_pattern(num: str) -> str:
    mapping = {"5": r"[5S＄$s]", "1": r"[1lI]", "2": r"[2zZ]"}
    return r"\s*".join(
        mapping.get(character, re.escape(character)) for character in num
    )


def _cpd_ocr_confusable_patterns(cpd: str) -> list[re.Pattern]:
    match = re.search(
        r"Compound\s+(\d+)(?:-\d+)?", _normalize_cpd_label(cpd), re.IGNORECASE
    )
    if not match or "5" not in match.group(1):
        return []
    fuzzy = _ocr_confusable_num_pattern(match.group(1))
    return [
        re.compile(pattern, re.IGNORECASE)
        for pattern in (
            rf"(?:实施例|化合物)\s*{fuzzy}(?![\dA-Za-z-])",
            rf"(?:得到|制备得到|分离制备得到)[^。\n]{{0,40}}(?:化合物)\s*{fuzzy}(?![\dA-Za-z-])",
        )
    ]


@lru_cache(maxsize=2048)
def _cpd_table_row_pattern(cpd: str) -> re.Pattern | None:
    match = re.search(
        r"Compound\s+(\d+(?:-\d+)?[A-Z]?)", _normalize_cpd_label(cpd), re.IGNORECASE
    )
    if not match:
        return None
    raw_number = match.group(1)
    number = re.escape(raw_number)
    patterns = [
        rf"(?:^|\n)\s*{number}(?=\s|$)(?![A-Za-z-])",
        rf"(?<![A-Za-z0-9])(?:[A-Z]|[1Il])\s*[-–—]\s*{number}(?!\d)",
    ]
    if len(raw_number) >= 2:
        patterns.append(
            rf"(?<![\dA-Za-z.-]){number}(?![\dA-Za-z.-])(?=.{{0,240}}\b\d{{3}}\.\d\b)"
        )
    return re.compile("|".join(patterns), re.IGNORECASE | re.DOTALL)


def _contiguous_page_blocks(pages: set[int]) -> list[list[int]]:
    blocks: list[list[int]] = []
    for page in sorted(pages):
        if not blocks or page != blocks[-1][-1] + 1:
            blocks.append([page])
        else:
            blocks[-1].append(page)
    return blocks


def _covered_active_cpds(
    pages: list[int],
    page_text_lookup: dict[int, str],
    active_cpds: list[str],
) -> dict[str, list[int]]:
    matched: dict[str, list[int]] = {}
    printed_ids = {
        page: _explicit_table_row_ids(page_text_lookup.get(page, "")) for page in pages
    }
    for raw_cpd in active_cpds:
        cpd = _normalize_cpd_label(raw_cpd)
        if not cpd:
            continue
        patterns = _cpd_patterns(cpd)
        row_pattern = _cpd_table_row_pattern(cpd)
        label = cpd.removeprefix("Compound ")
        hits = [
            page
            for page in pages
            if label in printed_ids[page]
            or any(
                pattern.search(page_text_lookup.get(page, "")) for pattern in patterns
            )
            or (
                row_pattern is not None
                and row_pattern.search(page_text_lookup.get(page, ""))
            )
        ]
        if hits:
            matched[cpd] = hits
    return matched


def _primary_activity_catalog(
    table_pages: set[int],
    texts: dict[int, str],
    active_cpds: list[str],
) -> tuple[list[int], dict[str, list[int]]]:
    """Keep strict-binder primary-catalog diagnostics, not segmentation selection."""
    blocks = _contiguous_page_blocks(table_pages)
    if not blocks:
        return [], {}
    block, _matches = max(
        ((block, _covered_active_cpds(block, texts, active_cpds)) for block in blocks),
        key=lambda item: (len(item[1]), len(item[0])),
    )
    pages = list(block)
    while pages and not _has_table_row_evidence(texts.get(pages[-1], "")):
        pages.pop()
    while pages and not _has_table_row_evidence(texts.get(pages[0], "")):
        pages.pop(0)
    matches = _covered_active_cpds(pages, texts, active_cpds)
    return (pages, matches) if len(matches) >= 6 else ([], {})


def _valid_pages(values: object, page_count: int | None) -> set[int]:
    if not isinstance(values, list):
        return set()
    return {
        page
        for page in values
        if type(page) is int and page >= 0 and (page_count is None or page < page_count)
    }


def locate_structure_pages(
    pdf_path: str,
    classification: dict,
    active_cpds: list[str],
    output_path: str = "",
    workers: int = 1,
    ocr_cache_path: str = "",
) -> dict:
    """Select all evidenced pages from one shared OCR observation authority.

    Fetch missing OCR only for classified synthesis/candidate pages. The existing
    full-PDF cache supplies independent catalogs/examples outside that window.
    No arbitrary full-PDF segmentation or chemistry binding is inferred here.
    """
    count = classification.get("page_count")
    page_count = count if type(count) is int and count > 0 else None
    synthesis = _valid_pages(classification.get("synthesis_pages", []), page_count)
    candidate_pool = sorted(
        synthesis | _valid_pages(classification.get("candidate_pages", []), page_count)
    )
    shared_cache = load_page_ocr_cache(ocr_cache_path)
    cached_texts = shared_cache.get("page_texts", {})
    cached_lines = shared_cache.get("ocr_line_map", {})
    if not isinstance(cached_texts, dict) or not isinstance(cached_lines, dict):
        raise TypeError("structure locator requires valid shared OCR collections")
    missing = [page for page in candidate_pool if str(page) not in cached_texts]
    if missing:
        built = build_page_ocr_cache(
            pdf_path, missing, workers=workers, min_native_chars=40
        )
        cached_texts.update(built.get("page_texts", {}))
        cached_lines.update(built.get("ocr_line_map", {}))
        if ocr_cache_path:
            save_page_ocr_cache(ocr_cache_path, shared_cache)
    texts = {
        int(key): value
        for key, value in cached_texts.items()
        if isinstance(key, str)
        and key.isascii()
        and key.isdigit()
        and isinstance(value, str)
        and value.strip()
        and (page_count is None or int(key) < page_count)
    }
    evidence = structure_page_evidence(texts, synthesis)
    if any(_is_singleton_main_compound_label(cpd) for cpd in active_cpds):
        for page, text in texts.items():
            if any(pattern.search(text) for pattern in _singleton_structure_patterns()):
                evidence.setdefault(page, "singleton_structure")
    selected = sorted(evidence)
    tables = {
        page
        for page, reason in evidence.items()
        if reason in {"numbered_structure_table", "structure_table_continuation"}
    }
    primary_pages, primary_matches = _primary_activity_catalog(
        tables, texts, active_cpds
    )
    matched = dict(primary_matches)
    unresolved = [
        cpd for cpd in active_cpds if _normalize_cpd_label(cpd) not in matched
    ]
    matched.update(_covered_active_cpds(selected, texts, unresolved))
    for raw_cpd in unresolved:
        cpd = _normalize_cpd_label(raw_cpd)
        if not cpd or cpd in matched:
            continue
        patterns = _cpd_ocr_confusable_patterns(cpd)
        hits = [
            page
            for page in selected
            if any(pattern.search(texts[page]) for pattern in patterns)
        ]
        if hits:
            matched[cpd] = hits
    active_norm = {cpd for raw in active_cpds if (cpd := _normalize_cpd_label(raw))}
    unmatched = sorted(active_norm - set(matched))
    unmatched_ratio = len(unmatched) / max(len(active_norm), 1)
    payload = {
        **artifact_identity(
            STRUCTURE_LOCATION_SCHEMA, STRUCTURE_LOCATION_SCHEMA_VERSION
        ),
        "coverage_policy": STRUCTURE_COVERAGE_POLICY,
        "candidate_pool": candidate_pool,
        "expanded_pool": selected,
        "selected_pages": selected,
        "structure_page_evidence": {str(page): evidence[page] for page in selected},
        "structure_table_pages": primary_pages,
        "detected_structure_table_pages": sorted(tables),
        "structure_table_covered_cpds": sorted(primary_matches),
        "structure_table_priority": bool(primary_pages),
        "structure_table_coverage_count": len(primary_matches),
        "matched_cpds": matched,
        "ocr_text_map": {str(page): texts[page] for page in selected},
        "ocr_line_map": {
            str(page): cached_lines[str(page)]
            for page in selected
            if cached_lines.get(str(page))
        },
        # No active-ID focus bands or paper-size assumptions: the worker segments
        # complete original pages. Strict downstream evidence/QC is unchanged.
        "crop_regions": {},
        "unmatched_cpds": unmatched,
        "reason": "full_structure_evidence_coverage"
        if selected
        else "no_structure_evidence",
        "broad_activity_table": len(active_cpds) >= 100 and unmatched_ratio >= 0.30,
        "unmatched_ratio": round(unmatched_ratio, 4),
    }
    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        write_json_atomic(output_path, payload)
    logger.info("Structure locator selected %s evidenced original pages", len(selected))
    return payload
