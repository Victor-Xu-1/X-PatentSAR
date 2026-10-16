"""Literal original catalogue roles, not final-product inference from numbers."""

import re

from .source_table_markers import TABLE_MARKER

_NONFINAL = re.compile(
    r"\b(?:intermediates?|starting\s+materials?|building\s+blocks?|reactants?|reagents?)\b"
    r"|中间体|中間体|起始原料|反应物|反応物|合成砌块",
    re.IGNORECASE,
)
_COMPOUNDS = re.compile(
    r"\b(?:compounds?|examples?)\b|化合物|实施例|実施例", re.IGNORECASE
)


def nonfinal_catalog_text(text):
    return bool(isinstance(text, str) and _NONFINAL.search(text))


def continuation_title(text):
    return bool(
        isinstance(text, str)
        and TABLE_MARKER.search(text)
        and re.search(
            r"\b(?:continued|continuation|cont\.)\b|续表|續表", text, re.IGNORECASE
        )
    )


def catalog_title_role(text):
    """A complete source title can declare a catalogue, never make up an ID."""
    if not isinstance(text, str) or len(text) > 2048:
        return "unknown"
    marker = TABLE_MARKER.search(text)
    if marker is None or text[: marker.start()].strip():
        return "unknown"
    title = text[marker.end() :]
    if nonfinal_catalog_text(title):
        return "nonfinal"
    return "compound" if _COMPOUNDS.search(title) else "unknown"
