"""Literal original catalogue roles, not final-product inference from numbers."""

import re

from .source_role_terms import CATALOG_COMPOUND_CJK, INTERMEDIATE_CJK
from .source_table_markers import TABLE_CAPTION_START, caption_table_marker

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


def nonfinal_catalog_text(text):
    return bool(isinstance(text, str) and _NONFINAL.search(text))


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
        return "unknown"
    marker = caption_table_marker(text)
    title = text[marker.end() if marker else start.end() :]
    nonfinal = tuple(_NONFINAL.finditer(title))
    compounds = tuple(_COMPOUNDS.finditer(title))
    if nonfinal:
        # "Intermediate compounds" is one declared nonfinal category. Separate
        # compound/product categories must not silently disappear with it.
        if any(
            not any(
                part.end() <= compound.start()
                and not title[part.end() : compound.start()].strip()
                for part in nonfinal
            )
            for compound in compounds
        ):
            return "mixed"
        return "nonfinal"
    return "compound" if compounds else "unknown"
