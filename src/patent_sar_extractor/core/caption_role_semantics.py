"""Literal original catalogue roles, not final-product inference from numbers."""

import re

from .source_role_terms import CATALOG_COMPOUND_CJK, INTERMEDIATE_CJK, role_words
from .source_table_markers import (
    TABLE_CAPTION_START,
    caption_table_marker,
    table_body_boundary,
)

_NONFINAL = re.compile(
    r"\b(?:intermediates?|starting\s+materials?|building\s+blocks?|reactants?|reagents?)\b"
    rf"|{INTERMEDIATE_CJK}|起始原料|反应物|反応物|合成砌块",
    re.IGNORECASE,
)
_COMPOUNDS = re.compile(
    r"\b(?:compounds?|examples?|(?:final|target|end)\s+products?)\b"
    rf"|{CATALOG_COMPOUND_CJK}",
    re.IGNORECASE,
)
_INTERMEDIATE_MODIFIER = re.compile(rf"intermediate|{INTERMEDIATE_CJK}", re.IGNORECASE)
_NEGATION = re.compile(
    r"\b(?:not|no|without|except|excluding)\s+"
    r"(?:(?:a|an|any|the|these|those|such)\s+)?$"
    r"|\bnon[-\s]+$|\bnon[-\s]*final[-\s]*$"
    r"|(?:非|不含|不包括|不包含|不是|并非|並非)\s*$",
    re.IGNORECASE,
)
_CATEGORY_NOUN = (
    rf"(?:(?:{_NONFINAL.pattern})(?:\s+compounds?)?|(?:{_COMPOUNDS.pattern}))"
)
_CATEGORY_TITLE = re.compile(
    rf"\s*(?:(?:selected|representative)\s+)?"
    rf"(?:(?:not|no|excluding|non[-\s]+)\s*)?{_CATEGORY_NOUN}"
    rf"(?:(?:\s*(?:and|or|&|/|,|，|和|与|與|及)\s*|\s+){_CATEGORY_NOUN})*[\s.:：]*",
    re.IGNORECASE,
)


def catalogue_title_boundary(text):
    """A table marker or whole category noun phrase, never an incidental mention."""
    return bool(
        isinstance(text, str)
        and len(text) <= 2048
        and (table_body_boundary(text) or _CATEGORY_TITLE.fullmatch(role_words(text)))
    )


def nonfinal_catalog_text(text):
    return bool(isinstance(text, str) and _NONFINAL.search(role_words(text)))


def continuation_title(text):
    return bool(
        isinstance(text, str)
        and caption_table_marker(text)
        and re.search(
            r"\b(?:continued|continuation)\b|\bcont\.(?=\W|$)|续表|續表",
            text,
            re.IGNORECASE,
        )
    )


def has_continuation_caption(text):
    """Page-text nomination only; qualified original windows still own roles."""
    return isinstance(text, str) and (
        continuation_title(text)
        or any(continuation_title(line) for line in text.splitlines())
    )


def catalog_title_role(text):
    """A complete source title can declare a catalogue, never make up an ID."""
    if not isinstance(text, str) or len(text) > 2048:
        return "unknown"
    start = TABLE_CAPTION_START.match(text)
    if start is None:
        if not _CATEGORY_TITLE.fullmatch(role_words(text)):
            return "unknown"
        title = role_words(text)
    else:
        marker = caption_table_marker(text)
        title = role_words(text[marker.end() if marker else start.end() :])
    nonfinal = tuple(_NONFINAL.finditer(title))
    compounds = tuple(_COMPOUNDS.finditer(title))
    # A negative category is not positive evidence for either admission or
    # exclusion. Keep it as an explicit conflict, including prefixed captions;
    # returning unknown would permit them to bypass the title veto.
    if any(_NEGATION.search(title[: part.start()]) for part in (*nonfinal, *compounds)):
        return "conflict"
    if nonfinal:
        # "Intermediate compounds" is one declared nonfinal category. Separate
        # compound/product categories must not silently disappear with it.
        if any(
            not any(
                part.end() <= compound.start()
                and _INTERMEDIATE_MODIFIER.fullmatch(part.group())
                and not title[part.end() : compound.start()].strip()
                for part in nonfinal
            )
            for compound in compounds
        ):
            return "mixed"
        return "nonfinal"
    return "compound" if compounds else "unknown"


def catalog_title_namespace(text):
    """A qualified catalogue's literal ID vocabulary, never a default namespace.

    Role "compound" also admits Example tables; it does not prove that Example7
    and Compound7 name the same entity. Generic product/structure words and mixed
    vocabularies deliberately provide no cross-source alias authority.
    """
    if catalog_title_role(text) != "compound":
        return ""
    words = role_words(text)
    namespaces = set()
    if re.search(r"\bcompounds?\b|化合物", words, re.IGNORECASE):
        namespaces.add("compound")
    if re.search(r"\bexamples?\b|实施例|實施例|実施例", words, re.IGNORECASE):
        namespaces.add("example")
    return next(iter(namespaces)) if len(namespaces) == 1 else ""
