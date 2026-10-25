"""Activity extraction facade: original cells/text -> observations -> one writer.

No table-number schema, numeric repair, activity pseudo-compound, alternate OCR
engine or fallback parser lives here. Physical grids own only their own sources;
independent text on the same page uses the existing text planner and writer.
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
from .activity_source_discovery import discover_activity_sources
from .activity_text import extract_text_tables
from .activity_text_capture import capture_text_page
from .activity_text_sources import required_text_page_keys
from .page_ocr_cache import load_page_ocr_cache, page_text, save_page_ocr_cache
from .text_ocr.configuration import owns_auxiliary_text

logger = logging.getLogger(__name__)
__all__ = ["ActivityRow", "OCRFixRule", "extract"]


@owns_auxiliary_text
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
        discovered = discover_activity_sources(doc, text_map)
        source_pages = sorted(set(pages) | set(discovered))
        for page_index in source_pages:
            if not str(text_map.get(str(page_index), "") or "").strip():
                # page_text uses the sole configured/shared OCR authority. Native
                # pages do not start a model. Independent source nomination
                # reads only original native text or already cached OCR.
                text_map[str(page_index)] = page_text(
                    doc[page_index], min_native_chars=1
                )
                dirty = True
        cells = extract_coordinate_tables(
            doc,
            coordinate_candidates(source_pages),
            header_resolver=header_resolver,
            page_texts=text_map,
        )

        def text_for_page(index):
            nonlocal dirty
            observed = str(text_map.get(str(index), "") or "")
            if not observed:
                observed = page_text(doc[index], min_native_chars=1)
                text_map[str(index)] = observed
                dirty = True
            return observed

        text_pages = sorted(
            int(key) - 1
            for key in required_text_page_keys(
                {
                    "seed_pages": sorted(set(source_pages) | cells.owned_pages),
                    "regions": cells.coverage,
                }
            )
        )
        for page_index in text_pages:
            text_for_page(page_index)
        text = extract_text_tables(
            text_pages,
            text_map,
            page_count=len(doc),
            page_reader=text_for_page,
            source_reader=lambda index, observed: capture_text_page(
                doc[index],
                observed,
                cache.get("ocr_line_map", {}).get(str(index), []),
                coordinate_regions=[
                    r for r in cells.coverage if r["page_no"] == index + 1
                ],
            ),
            coordinate_regions=cells.coverage,
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
    coverage = coverage_packet(
        pages,
        [*cells.coverage, *text.coverage],
        rows,
        discovered_pages=discovered,
        text_pages=text.text_pages,
        text_sources=text.text_sources,
    )
    save_results(
        rows,
        output,
        profile,
        coverage=coverage,
        unresolved_rows=cells.unresolved_rows,
        header_observations=cells.header_observations,
        role_observations=cells.role_observations,
    )
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
