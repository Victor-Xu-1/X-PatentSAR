"""Pure page-selection evidence; no activity-based omission or binding authority."""

from __future__ import annotations

import re
from functools import lru_cache

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
STRUCTURE_COLUMN_RE = re.compile(
    r"\b(?:structure|formula)\b|结构式|化学结构|结构表", re.IGNORECASE
)
NUMBER_COLUMN_RE = re.compile(
    r"化合物编号|\b(?:compound|cmpd|cpd)\s*(?:no\.?|number|id|#)\b",
    re.IGNORECASE,
)
ADJACENT_STRUCTURE_HEADER_RE = re.compile(
    r"\b(?:compound|cmpd|cpd|example|intermediate)s?\s+"
    r"(?:structures?|formulae?)\b|化合物\s*(?:结构|列表)|结构列表|结构表",
    re.IGNORECASE,
)
NUMBERED_LABEL_RE = re.compile(
    r"\b(?:compound|cmpd|cpd|example|intermediate)\s*[-:]?\s*"
    r"(?:[A-Z]\s*[-–—]\s*)?(?:\d+|[S$＄]\d+)(?:-\d+)?[A-Z]?(?![\w-])|"
    r"(?:实施例|化合物|中间体|制备例|合成例)\s*(?:\d+|[S$＄]\d+)(?:-\d+)?[A-Z]?",
    re.IGNORECASE,
)
CHEMISTRY_CONTEXT_RE = re.compile(
    r"\b(?:NMR|HNMR|LCMS|LC[-\s]?MS|HPLC|mmol|synthesis|preparation|"
    r"purified|reagents?|stirred|stirring|dissolved|dissolving)\b|"
    r"\bMS\s*(?:m/z|\(\s*ESI)|\bm/z\b|合成|制备|收率|产率|反应|纯化",
    re.IGNORECASE,
)
NON_STRUCTURE_SECTION_RE = re.compile(
    r"\bWhat\s+is\s+claimed\b|权利要求|\bBACKGROUND\b|\bSUMMARY\b|"
    r"检索报告|PCT/ISA|生物测试|测试例\s*\d+|\bTest\s*Example\b",
    re.IGNORECASE,
)
ATOM_LABEL_RE = re.compile(r"(?<![A-Za-z])(?:HN|NH|OH|HO|Cl|Br|[NOSFP])(?![A-Za-z])")
PUNCTUATED_ID_RE = re.compile(
    r"(?<![\w.])([1-9]\d{0,3}[A-Z]?)\.(?=\s|$)", re.IGNORECASE
)


@lru_cache(maxsize=512)
def _is_structure_table_page(text: str) -> bool:
    """Retain the established numbered-table/continuation observation rule."""
    value = str(text or "")
    if not value.strip():
        return False
    if STRUCTURE_TABLE_HEADER_RE.search(value):
        return True
    row_ids = len(STRUCTURE_TABLE_ROW_ID_RE.findall(value))
    masses = len(STRUCTURE_TABLE_MASS_RE.findall(value))
    numbered_compounds = len(re.findall(r"化合物\s*\d+", value, re.IGNORECASE))
    english_compounds = len(re.findall(r"\bCompound\s*\d+\b", value, re.IGNORECASE))
    flattened_hits = len(STRUCTURE_TABLE_FLATTENED_ID_MASS_RE.findall(value))
    chem_name_hits = len(STRUCTURE_TABLE_CHEM_NAME_RE.findall(value))
    series_id_hits = len(STRUCTURE_TABLE_SERIES_ID_RE.findall(value))
    compact_length = len(re.sub(r"\s+", "", value))
    explicit_series_header = bool(
        re.search(
            r"(?:[A-Z]|[1Il])\s*-\s*#.{0,48}\bStructure\b|"
            r"\bTable\s*\d+\s*[.:]?\s*(?:Exemplary\s+)?Compounds?\b",
            value,
            re.IGNORECASE | re.DOTALL,
        )
    )
    prose = bool(STRUCTURE_PROSE_ASSAY_RE.search(value))
    return (
        (row_ids >= 3 and masses >= 3)
        or (numbered_compounds >= 2 and masses >= 2)
        or (english_compounds >= 6 and not prose)
        or (row_ids >= 8 and not prose)
        or (flattened_hits >= 3 and masses >= 3 and chem_name_hits >= 2 and not prose)
        or explicit_series_header
        or (series_id_hits >= 2 and compact_length <= 500)
        or (series_id_hits == 1 and compact_length <= 100)
    )


def _explicit_table_row_ids(text: str) -> set[str]:
    """Punctuated cells require a table header, never chemical locants."""
    if not STRUCTURE_TABLE_HEADER_RE.search(text):
        return set()
    return {match.group(1).upper() for match in PUNCTUATED_ID_RE.finditer(text)}


def _has_table_row_evidence(text: str) -> bool:
    return bool(
        STRUCTURE_TABLE_SERIES_ID_RE.search(text) or _explicit_table_row_ids(text)
    )


def _numbered_structure_table(text: str) -> bool:
    if not _is_structure_table_page(text):
        return False
    if STRUCTURE_COLUMN_RE.search(text):
        # Formula prose plus claim numbers/chemical locants is not a table.
        # Require an actual number column or adjacent column headings with
        # independently observed row IDs; "compound of Formula" is insufficient.
        return bool(
            NUMBER_COLUMN_RE.search(text)
            or (
                ADJACENT_STRUCTURE_HEADER_RE.search(text)
                and _has_table_row_evidence(text)
            )
        )
    # A compound-number column also describes biology tables. It alone cannot
    # establish a structural source, even if the page is classified synthesis.
    if STRUCTURE_PROSE_ASSAY_RE.search(text):
        return False
    return bool(
        STRUCTURE_TABLE_SERIES_ID_RE.search(text)
        or (
            len(STRUCTURE_TABLE_MASS_RE.findall(text)) >= 2
            and len(STRUCTURE_TABLE_CHEM_NAME_RE.findall(text)) >= 2
        )
        or len(ATOM_LABEL_RE.findall(text)) >= 2
    )


def structure_page_evidence(
    page_texts: dict[int, str],
    synthesis_pages: set[int],
) -> dict[int, str]:
    """Select every supported page; expand only evidenced adjacent continuations."""
    evidence: dict[int, str] = {}
    for page, text in page_texts.items():
        if _numbered_structure_table(text):
            evidence[page] = "numbered_structure_table"
        elif (
            NUMBERED_LABEL_RE.search(text)
            and not NON_STRUCTURE_SECTION_RE.search(text)
            and (
                CHEMISTRY_CONTEXT_RE.search(text)
                or len(ATOM_LABEL_RE.findall(text)) >= 2
            )
        ):
            evidence[page] = "numbered_synthesis_or_caption"
    frontier = list(evidence)
    while frontier:
        page = frontier.pop()
        for neighbor in (page - 1, page + 1):
            if neighbor in evidence:
                continue
            text = page_texts.get(neighbor, "")
            if not text or NON_STRUCTURE_SECTION_RE.search(text):
                continue
            table_continuation = (
                evidence[page]
                in {"numbered_structure_table", "structure_table_continuation"}
                and not STRUCTURE_PROSE_ASSAY_RE.search(text)
                and len(PUNCTUATED_ID_RE.findall(text)) >= 2
                and len(ATOM_LABEL_RE.findall(text)) >= 2
            )
            synthesis_continuation = (
                evidence[page]
                in {"numbered_synthesis_or_caption", "synthesis_continuation"}
                and neighbor in synthesis_pages
                and bool(CHEMISTRY_CONTEXT_RE.search(text))
            )
            if table_continuation or synthesis_continuation:
                evidence[neighbor] = (
                    "structure_table_continuation"
                    if table_continuation
                    else "synthesis_continuation"
                )
                frontier.append(neighbor)
    return evidence
