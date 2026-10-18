"""Literal section roles; an experiment number is not a molecular identity."""

from __future__ import annotations

import re
from typing import Any

from .activity_identity import PRINTED_ID, printed_identifier_key
from .printed_identifiers import identifier_width
from .source_role_terms import (
    INTERMEDIATE_CJK,
    INTERMEDIATE_PLURAL,
    INTERMEDIATE_SINGULAR,
    INTERMEDIATE_TERM,
    is_intermediate_kind,
)

_HEADING = re.compile(
    r"^(?:\[\s*\d{1,8}\s*\]\s*)?"
    r"(?P<preparation>(?:(?:Synthesis|Preparation)\s+(?:of\s+)?)?)"
    r"(?:Exemplary\s+)?"
    rf"(?P<kind>Compound|Cmpd|Cpd|Example|{INTERMEDIATE_SINGULAR}|实施例|化合物)\s*[-:.：]?\s*"
    rf"(?P<identifier>{PRINTED_ID})(?![\w/-])(?P<tail>.*)$",
    re.IGNORECASE,
)
_SEPARATOR = r"\s*(?:,\s*(?:and\s+)?|and\s+|&\s*|和|及|、)\s*"
_GROUP = re.compile(
    r"^(?:\[\s*\d{1,8}\s*\]\s*)?"
    r"(?P<preparation>(?:(?:Synthesis|Preparation)\s+(?:of\s+)?)?)"
    r"(?:Exemplary\s+)?"
    rf"(?P<kind>Compounds|Cmpds|Cpds|Examples|{INTERMEDIATE_PLURAL}|实施例|化合物)\s*[-:.：]?\s*"
    rf"(?P<members>{PRINTED_ID}(?:{_SEPARATOR}{PRINTED_ID}){{1,31}})"
    r"(?![\w/-])(?P<tail>.*)$",
    re.IGNORECASE,
)
_LIST_START = re.compile(
    r"^(?:\[\s*\d{1,8}\s*\]\s*)?"
    r"(?:(?:Synthesis|Preparation)\s+(?:of\s+)?)?(?:Exemplary\s+)?"
    rf"(?:Compounds?|Cmpds?|Cpds?|Examples?|{INTERMEDIATE_TERM}|实施例|化合物)\s*[-:.：]?\s*",
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
_INTERMEDIATE_TARGET = re.compile(
    r"^(?:(?:Synthesis|Preparation|制备|合成)\s*(?:of\s+)?)?"
    rf"{INTERMEDIATE_SINGULAR}(?=[\s:.：0-9-]|$)",
    re.IGNORECASE,
)
_PROCEDURE = re.compile(
    r"^(?:\[\s*\d{1,8}\s*\]|(?:Step|Stage|步骤|中间体|Intermediate)\b|"
    r"[A-Z][.)]\s|To\s+(?:a|an|the)\s|A\s+(?:solution|mixture)\b|"
    r"The\s+(?:reaction|mixture)\b)",
    re.IGNORECASE,
)


def procedure_heading_boundary(text):
    """One literal procedure stop shared by single/plural original declarations."""
    return bool(_PROCEDURE.match(str(text).strip()))


def section_heading(text: object) -> dict[str, Any] | None:
    """Observe a bounded literal heading, never infer a role from its number."""
    raw = str(text or "").strip()
    if len(raw) > 4096:
        return None
    source = " ".join(identifier_width(raw).split())
    match = _GROUP.fullmatch(source) or _HEADING.fullmatch(source)
    if not match:
        return None
    tail = match["tail"].strip()
    if match.re is _GROUP and re.match(
        rf"^{_SEPARATOR}{PRINTED_ID}", tail, re.IGNORECASE
    ):
        raise ValueError("Original heading exceeds its 32 literal member bound")
    if tail and not (
        tail[0] in ":.：)" or _PREPARATION.match(tail) or _ASSAY_TITLE.match(tail)
    ):
        return None
    if re.match(r"^[.:：)]?\s*(?:and\b|to\s+\d|through\b|及|和)", tail, re.IGNORECASE):
        return None
    title = tail.lstrip(".:：) ")
    kind = match["kind"].lower()
    if match.re is _GROUP and kind.endswith("s"):
        kind = kind[:-1]
    role = "compound_heading"
    if (
        is_intermediate_kind(kind)
        or kind in {"example", "实施例"}
        and _INTERMEDIATE_TARGET.match(title)
    ):
        role = "intermediate_section"
    elif kind in {"example", "实施例"} and _ASSAY_TITLE.search(title):
        # A synthesis/probe title with an assay word is conflicting evidence,
        # not a free exemption from ownership validation.
        role = (
            "ambiguous_heading"
            if match["preparation"] or _PREPARATION.match(title)
            else "assay_section"
        )
    members = (
        [
            printed_identifier_key(item)
            for item in re.split(_SEPARATOR, match["members"], flags=re.IGNORECASE)
        ]
        if match.re is _GROUP
        else [printed_identifier_key(match["identifier"])]
    )
    if not all(members):
        return None
    return {
        "identifier": members[0] if len(members) == 1 else "",
        **({"identifiers": members} if len(members) > 1 else {}),
        "label_kind": kind,
        "role": role,
        "line_text": raw,
    }


def heading_members(observation: dict | None) -> list[str]:
    """Only explicit literal members; never infer a range or figure order."""
    if not observation:
        return []
    return list(observation.get("identifiers", [observation["identifier"]]))


def section_body_boundary(text: object) -> dict[str, Any] | None:
    """An explicit procedure/assay title, not an ordinary printed row label."""
    observed = section_heading(text)
    if observed is None:
        return None
    source = " ".join(identifier_width(str(text or "").strip()).split())
    match = _GROUP.fullmatch(source) or _HEADING.fullmatch(source)
    title = match["tail"].lstrip(".:：) ")
    return (
        observed
        if (
            match["preparation"]
            or _PREPARATION.match(title)
            or observed["role"] == "assay_section"
        )
        else None
    )


def heading_list_hint(text: object) -> bool:
    """A bounded literal list/range locator, never a declaration or expansion."""
    raw = str(text or "").strip()
    if len(raw) > 4096:
        return False
    raw = identifier_width(raw)
    start = _LIST_START.match(raw)
    if start is None:
        return False
    body = raw[start.end() :]
    identifiers = list(re.finditer(rf"(?<![\w/-]){PRINTED_ID}(?![\w/-])", body))
    if not identifiers:
        return False
    remainder = re.sub(rf"(?<![\w/-]){PRINTED_ID}(?![\w/-])", "", body)
    remainder = re.sub(
        rf"\b(?:Compounds?|Cmpds?|Cpds?|Examples?|Intermediates?)\b|实施例|化合物|{INTERMEDIATE_CJK}",
        "",
        remainder,
        flags=re.IGNORECASE,
    )
    return bool(
        re.fullmatch(
            r"(?:[\s,;:&、和及~\-–—]|\band\b|\bto\b|\bthrough\b)*",
            remainder,
            re.IGNORECASE,
        )
    )


def heading_assay_tail(text: object) -> bool:
    """A literal non-numbered assay-title line can continue an Example title."""
    raw = str(text or "").strip()
    return bool(
        len(raw) <= 4096 and _ASSAY_TITLE.match(raw) and not re.search(r"\d", raw)
    )


def nonfinal_original_label(text: object) -> bool:
    """A literal nonfinal role may not be relabelled by matching OCR strings.

    This is a role guard, not an intermediate-ID or I-prefix guess. Compound
    namespaces and references to an intermediate in a final synthesis title do
    not change the declared source role. Unrecognized titles remain unrecognized.
    """
    raw = str(text or "").strip()
    if len(raw) > 4096:
        return False
    observed = section_heading(raw)
    if observed:
        return observed["role"] in {
            "intermediate_section",
            "assay_section",
            "ambiguous_heading",
        }
    return bool(_INTERMEDIATE_TARGET.match(identifier_width(raw)))
