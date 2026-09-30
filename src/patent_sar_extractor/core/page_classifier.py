"""
Deterministic page classifier for the production pipeline.
"""

import logging
import re
from pathlib import Path

import fitz

from patent_sar_extractor.artifact_io import write_json_atomic
from patent_sar_extractor.contracts import (
    PAGE_CLASSIFICATION_SCHEMA,
    PAGE_CLASSIFICATION_SCHEMA_VERSION,
    artifact_identity,
)
from patent_sar_extractor.core.page_ocr_cache import update_page_ocr_cache
from patent_sar_extractor.core.review_excerpt import infer_candidate_page_window

logger = logging.getLogger(__name__)
CLASSIFIER_TEXT_WINDOW = 2400

# ── 关键词规则 ──
ACTIVITY_RE = re.compile(
    r"IC50|DC50|EC50|Ki\b|Kd\b|Dmax|nM\b|µM|μM|GI50|CC50|pIC50|"
    r"抑制率|结合率|降解率|表\s*\d|Table\s+\d.*activit",
    re.IGNORECASE,
)
SYNTHESIS_RE = re.compile(
    r"实施例\s*\d+|Example\s+\d+|合成例|制备例|"
    r"MS\s*m/z|NMR|LCMS|HPLC|收率|产率|m\.p\.|"
    r"Synthesis\s+of|Preparation\s+of|"
    r"\bEx\.?\s*Structure\b|"
    r"化合物编号\s*结构式|结构式\s*化学名称|LC-MS\s*$|"
    r"化合物编号|结构式|化学名称",
    re.IGNORECASE,
)
STRUCTURE_TABLE_RE = re.compile(
    r"化合物编号\s*结构式\s*化学名称|结构式\s*化学名称\s*LC-MS|"
    r"Compound\s*(?:No\.?|Number)\s*Structure|Structure\s*Chemical\s*Name|"
    r"\bEx\.?\s*Structure\b|"
    r"化合物编号|结构式|化学名称|LC-MS",
    re.IGNORECASE,
)
STRUCTURE_TABLE_CONTINUATION_ID_RE = re.compile(r"(?:^|\n)\s*\d{1,3}(?=\s|$)")
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
NON_CORE_RE = re.compile(
    r"权利要求|权利要求书|^What is claimed|"
    r"BACKGROUND|SUMMARY|DRAWING|检索报告|PCT/ISA",
    re.IGNORECASE | re.MULTILINE,
)
BIOASSAY_RE = re.compile(r"生物测试|测试例\s*\d+|Test\s*Example", re.IGNORECASE)
CPD_PREFIX_PATTERNS = [
    (r"实施例\s*(\d+)", "实施例"),
    (r"化合物\s*(\d+)", "化合物"),
    (r"Cpd[-\s]?(\d+)", "Cpd-"),
    (r"Example[-\s]+(\d+)", "Example"),
    (r"Compound[-\s]+(\d+)", "Compound"),
    (r"Intermediate\s+(\d+)", "Intermediate"),
]


def _structure_table_continuation_score(text: str) -> tuple[int, int, int]:
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    line_id_hits = sum(1 for line in lines if re.match(r"^\d{1,3}\b", line))
    line_mass_hits = sum(1 for line in lines if STRUCTURE_TABLE_MASS_RE.search(line))
    chinese_cpd_hits = len(re.findall(r"化合物\s*\d+", text, re.IGNORECASE))
    return line_id_hits, line_mass_hits, chinese_cpd_hits


def _flattened_structure_table_score(text: str) -> tuple[int, int, int]:
    value = str(text or "")
    id_mass_hits = len(STRUCTURE_TABLE_FLATTENED_ID_MASS_RE.findall(value))
    mass_hits = len(STRUCTURE_TABLE_MASS_RE.findall(value))
    chem_name_hits = len(STRUCTURE_TABLE_CHEM_NAME_RE.findall(value))
    return id_mass_hits, mass_hits, chem_name_hits


def _is_flattened_structure_table_continuation(text: str) -> bool:
    id_mass_hits, mass_hits, chem_name_hits = _flattened_structure_table_score(text)
    return id_mass_hits >= 3 and mass_hits >= 3 and chem_name_hits >= 2


def classify_pdf(pdf_path: str, output_dir: str, force_ocr_cache: bool = False) -> dict:
    """Classify pages with deterministic OCR and keyword rules.

    The production classifier never delegates page ownership to an LLM.  The
    returned ``candidate_pages`` list is a diagnostic window in original-PDF page
    coordinates; it is not a second working document.
    """
    with fitz.open(pdf_path) as document:
        total = len(document)
    logger.info(f"📄 分析: {pdf_path} ({total} 页)")
    cache_path = str(Path(output_dir) / "page_ocr_cache.json")

    # Step 1: OCR 全部页，缓存到共享资产
    cache = update_page_ocr_cache(
        pdf_path,
        list(range(total)),
        cache_path,
        workers=4,
        min_native_chars=30,
        force=force_ocr_cache,
    )
    pages_text_map = {int(k): v for k, v in cache.get("page_texts", {}).items() if str(k).isdigit()}
    pages_text = [str(pages_text_map.get(i, ""))[:CLASSIFIER_TEXT_WINDOW] for i in range(total)]
    logger.info(f"  RapidOCR/缓存完成 ({total} 页)")

    # Step 2: 关键词分类（策略：宁可多不能少，只明确排除非核心页）
    synthesis_pages = []
    activity_pages = []
    other_pages = []
    cpd_counts = {p[1]: 0 for p in CPD_PREFIX_PATTERNS}

    for i, text in enumerate(pages_text):
        is_activity = bool(ACTIVITY_RE.search(text))
        is_synthesis = bool(SYNTHESIS_RE.search(text))
        is_non_core = bool(NON_CORE_RE.search(text))
        is_structure_table = bool(STRUCTURE_TABLE_RE.search(text))

        cpd_dense = len(re.findall(r"Cpd[-\s]?\d+|实施例\s*\d+", text, re.IGNORECASE))
        chinese_cpd_dense = len(re.findall(r"化合物\s*\d+", text, re.IGNORECASE))
        nums = len(re.findall(r"\b\d{1,5}\b", text))
        is_data_table = cpd_dense >= 10 and nums >= cpd_dense * 2
        structure_table_ids = len(STRUCTURE_TABLE_CONTINUATION_ID_RE.findall(text))
        structure_table_masses = len(STRUCTURE_TABLE_MASS_RE.findall(text))
        line_id_hits, line_mass_hits, line_cpd_hits = _structure_table_continuation_score(text)
        flattened_table = _is_flattened_structure_table_continuation(text)
        is_structure_table_page = is_structure_table and (
            chinese_cpd_dense >= 2
            or len(re.findall(r"\b\d+(?:\.\d+)?\b", text)) >= 6
        )
        is_structure_table_continuation = (
            (
                structure_table_ids >= 3
                and structure_table_masses >= 3
            )
            or (
                line_id_hits >= 3
                and line_mass_hits >= 3
            )
            or (
                line_cpd_hits >= 2
                and line_mass_hits >= 2
            )
            or flattened_table
        ) and not is_activity

        if is_activity or is_data_table:
            activity_pages.append(i)
        if is_synthesis or is_structure_table_page or is_structure_table_continuation:
            synthesis_pages.append(i)

        for pat, prefix in CPD_PREFIX_PATTERNS:
            m = re.findall(pat, text, re.IGNORECASE)
            if m:
                cpd_counts[prefix] = cpd_counts.get(prefix, 0) + len(m)

    # Extend structure-table runs across continuation pages until a clear
    # section break (bioassay / claims) appears. This helps scanned Chinese
    # patents where only the first table page has a strong header signal.
    synthesis_set = set(synthesis_pages)
    for start_idx in sorted(list(synthesis_set)):
        text = pages_text[start_idx]
        if not STRUCTURE_TABLE_RE.search(text):
            continue
        for next_idx in range(start_idx + 1, total):
            next_text = pages_text[next_idx]
            if not next_text.strip():
                continue
            if NON_CORE_RE.search(next_text) or BIOASSAY_RE.search(next_text):
                break
            continuation_ids = len(STRUCTURE_TABLE_CONTINUATION_ID_RE.findall(next_text))
            continuation_masses = len(STRUCTURE_TABLE_MASS_RE.findall(next_text))
            line_id_hits, line_mass_hits, continuation_cpds = _structure_table_continuation_score(next_text)
            flattened_table = _is_flattened_structure_table_continuation(next_text)
            if continuation_ids >= 2 and continuation_masses >= 2:
                synthesis_set.add(next_idx)
                continue
            if line_id_hits >= 2 and line_mass_hits >= 2:
                synthesis_set.add(next_idx)
                continue
            if continuation_cpds >= 2 and continuation_masses >= 2:
                synthesis_set.add(next_idx)
                continue
            if flattened_table and not ACTIVITY_RE.search(next_text):
                synthesis_set.add(next_idx)
                continue
            break
    synthesis_pages = sorted(synthesis_set)

    # Cpd 前缀
    valid_prefixes = {k: v for k, v in cpd_counts.items() if v > 0}
    best_prefix = max(valid_prefixes, key=valid_prefixes.get) if valid_prefixes else "Cpd-"

    best_pattern = r"Cpd[-\s]?(\d+)"
    for pat, prefix in CPD_PREFIX_PATTERNS:
        if prefix == best_prefix:
            best_pattern = pat
            break

    boundary = infer_candidate_page_window(
        pages_text,
        synthesis_pages=synthesis_pages,
        activity_pages=activity_pages,
    )
    candidate_pages = boundary.get("candidate_pages", [])

    other_pages = sorted(set(range(total)) - set(synthesis_pages) - set(activity_pages))
    result = {
        **artifact_identity(PAGE_CLASSIFICATION_SCHEMA, PAGE_CLASSIFICATION_SCHEMA_VERSION),
        "synthesis_pages": sorted(synthesis_pages),
        "activity_pages": sorted(activity_pages),
        "other_pages": sorted(other_pages),
        "candidate_pages": sorted(candidate_pages),
        "cpd_prefix": best_prefix,
        "cpd_pattern": best_pattern,
        "page_count": total,
        "candidate_boundary": boundary,
        "ocr_cache_path": cache_path,
    }

    logger.info(f"  ✅ 关键词: {len(synthesis_pages)} 合成, {len(activity_pages)} 活性")
    logger.info(f"  Cpd 前缀: '{best_prefix}'")

    # 保存
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    write_json_atomic(out_path / "page_classification.json", result)

    return result
