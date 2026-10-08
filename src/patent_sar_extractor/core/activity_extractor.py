"""Activity extraction facade: original cells/text -> observations -> one writer.

No table-number schema, numeric repair, activity pseudo-compound, alternate OCR
engine or fallback parser lives here. Recognized cell pages have sole ownership.
Application acceptance and public contract/version policy remain outside core.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import fitz

from .activity_artifacts import save_results
from .activity_coordinates import coordinate_candidates, extract_coordinate_tables
from .activity_coverage import coverage_packet
from .activity_header_roles import HeaderResolver
from .activity_models import ActivityRow, OCRFixRule
from .activity_observations import (
    DEFAULT_OCR_FIXES,
    apply_ocr_fixes,
    merge_rows,
    validate_rows,
)
from .activity_text import extract_text_tables
from .page_ocr_cache import load_page_ocr_cache, page_text, save_page_ocr_cache

logger = logging.getLogger(__name__)
__all__ = ["ActivityRow", "OCRFixRule", "extract"]


def extract(
    pdf_path: str,
    profile: dict,
    output_dir: str,
    ocr_fix_rules: list[OCRFixRule] | None = None,
    max_cpd_num: int = 0,
    include_intermediates: bool = False,
    header_resolver: HeaderResolver | None = None,
) -> dict:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    raw_pages = profile.get("activity_pages")
    if not isinstance(raw_pages, list) or any(
        type(p) is not int or p < 0 for p in raw_pages
    ):
        raise ValueError("Malformed classified activity_pages")
    cache_path = str(profile.get("ocr_cache_path", "") or "")
    cache = (
        load_page_ocr_cache(cache_path)
        if cache_path
        else {"page_texts": {}, "ocr_line_map": {}}
    )
    text_map = cache.setdefault("page_texts", {})
    dirty = False
    with fitz.open(pdf_path) as doc:
        pages = sorted(set(raw_pages))
        if any(page >= len(doc) for page in pages):
            raise ValueError("Classified activity page is outside the original PDF")
        for page_index in pages:
            if not str(text_map.get(str(page_index), "") or "").strip():
                # page_text uses the sole configured/shared OCR authority. Native
                # pages do not start a model and an empty classified set is not
                # silently expanded into an all-document scan.
                text_map[str(page_index)] = page_text(
                    doc[page_index], min_native_chars=1
                )
                dirty = True
        cells = extract_coordinate_tables(
            doc, coordinate_candidates(pages, text_map), header_resolver=header_resolver
        )
        text = extract_text_tables(
            [p for p in pages if p not in cells.owned_pages], text_map
        )
    if dirty and cache_path:
        save_page_ocr_cache(cache_path, cache)
    rows = merge_rows([*cells.rows, *text.rows])
    if not include_intermediates:
        rows = [
            r for r in rows if not re.fullmatch(r"Int[-\s]?\d+", r.cpd, re.IGNORECASE)
        ]
    for row in rows:
        apply_ocr_fixes(
            row,
            ocr_fix_rules if ocr_fix_rules is not None else DEFAULT_OCR_FIXES,
            max_cpd_num=max_cpd_num,
        )
    validate_rows(rows)
    tables = cells.tables + text.tables
    coverage = coverage_packet(pages, [*cells.coverage, *text.coverage], rows)
    save_results(rows, output, profile, coverage=coverage)
    headers = list(dict.fromkeys([*cells.headers, *text.headers]))
    logger.info(
        "Activity observations: %s rows, %s cell-owned pages",
        len(rows),
        len(cells.owned_pages),
    )
    return {
        "rows": rows,
        "coverage": coverage,
        "n_rows": len(rows),
        "n_unique_cpds": len({r.cpd for r in rows}),
        "tables": tables,
        "column_layout": {"type": "observed", "split_xs": []},
        "column_headers": headers,
        "col_classes": [],
        "output_dir": str(output),
    }
