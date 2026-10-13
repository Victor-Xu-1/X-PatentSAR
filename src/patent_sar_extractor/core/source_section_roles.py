"""Literal section roles; an experiment number is not a molecular identity."""

from __future__ import annotations

import re
import unicodedata

from .activity_identity import PRINTED_ID, printed_identifier_key

_HEADING = re.compile(
    r"^(?:\[\s*\d{1,8}\s*\]\s*)?"
    r"(?P<preparation>(?:(?:Synthesis|Preparation)\s+(?:of\s+)?)?)"
    r"(?P<kind>Compound|Cmpd|Cpd|Example|实施例|化合物)\s*[-:.：]?\s*"
    rf"(?P<identifier>{PRINTED_ID})(?![\w/-])(?P<tail>.*)$",
    re.IGNORECASE,
)
_ASSAY_TITLE = re.compile(
    r"\bassay\b|\bbiological\s+(?:evaluation|assessment|activity|testing)\b|"
    r"\b(?:HTRF|HiBiT|NanoBiT|FACS|pharmacokinetics?|pharmacokinetic)\b|"
    r"\bin\s+vivo\s+(?:efficacy|evaluation|study|activity)\b|"
    r"\b(?:cell|cellular)\s+(?:proliferation|viability|degradation)\b|"
    r"生物(?:评价|评估|实验|活性)|药代(?:动力学|研究)|活性测定",
    re.IGNORECASE,
)
_PREPARATION = re.compile(
    r"^(?:Synthesis|Preparation|制备|合成)(?:\b|(?=[\u4e00-\u9fff]))", re.IGNORECASE
)


def section_heading(text: object) -> dict[str, str] | None:
    """Observe a bounded literal heading, never infer a role from its number."""
    raw = str(text or "").strip()
    if len(raw) > 4096:
        return None
    match = _HEADING.fullmatch(unicodedata.normalize("NFKC", raw))
    if not match:
        return None
    tail = match["tail"].strip()
    if tail and not (tail[0] in ":.：)" or _PREPARATION.match(tail)):
        return None
    if re.match(r"^[.:：)]?\s*(?:and\b|to\s+\d|through\b|及|和)", tail, re.IGNORECASE):
        return None
    title = tail.lstrip(".:：) ")
    kind = match["kind"].lower()
    role = "compound_heading"
    if kind in {"example", "实施例"} and _ASSAY_TITLE.search(title):
        # A synthesis/probe title with an assay word is conflicting evidence,
        # not a free exemption from ownership validation.
        role = (
            "ambiguous_heading"
            if match["preparation"] or _PREPARATION.match(title)
            else "assay_section"
        )
    return {
        "identifier": printed_identifier_key(match["identifier"]),
        "label_kind": kind,
        "role": role,
        "line_text": raw,
    }
