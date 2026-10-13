"""Conservative method-only source proof, never an assay-result parser."""

from __future__ import annotations

import re

from .activity_identity import PRINTED_ID
from .source_section_roles import section_heading
from .source_table_markers import TABLE_MARKER

_PROCEDURE = re.compile(
    r"\b(?:seeded|plated|added|incubated|diluted|dispensed|washed|prepared|read)\b|"
    r"接种|孵育|加入|稀释|洗涤",
    re.IGNORECASE,
)
_RESULT = re.compile(
    r"\b(?:results?|showed|demonstrated|exhibited|observed|obtained)\b|"
    r"(?:IC50|EC50|DC50|Ki|Kd|Dmax|Imax)\s*(?:=|[<>≤≥]|was|of\s+\d)|"
    r"结果|显示|观察到",
    re.IGNORECASE,
)
_ROW = re.compile(
    rf"^\s*(?:(?:Compound|Cpd|Cmpd|Example|化合物|实施例)\s*)?{PRINTED_ID}"
    r"\s+(?:[<>≤≥]?\s*\d|[A-G](?=\s|$))",
    re.IGNORECASE,
)


def method_page_evidence(text: str) -> str:
    """Require an explicit assay title and procedure, with no reported source.

    The caller must already have physically inspected the page for grids. A
    table mention, row-like observation or result claim remains unresolved even
    if no parser could read it. Unknown styles never receive this exemption.
    """
    if not isinstance(text, str) or not text.strip() or len(text) > 100000:
        return ""
    if TABLE_MARKER.search(text) or _RESULT.search(text):
        return ""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    observations = [(line, section_heading(line)) for line in lines]
    if not any(item and item["role"] == "assay_section" for _, item in observations):
        return ""
    if any(
        item and item["role"] != "assay_section" or not item and _ROW.match(line)
        for line, item in observations
    ):
        return ""
    if len({match.group().lower() for match in _PROCEDURE.finditer(text)}) < 2:
        return ""
    # Store one bounded raw window, not a guessed role without source text. If
    # the title/procedure cannot fit, retain the normal unresolved page instead.
    window = text.strip()[:1024]
    if window != text.strip() and not method_page_evidence(window):
        return ""
    return window
