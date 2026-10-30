"""Closed assay-word typography, never fuzzy scientific identifier matching."""

import re

from .activity_context_values import context_values
from .activity_header_metrics import METRIC, normalize_metric_text

# Existing assay vocabulary only. Manufacturer spellings are documented in
# OPERATIONS; no target, endpoint, unit, compound or arbitrary word is corrected.
_ASSAY_WORDS = frozenset({"htrf", "hibit", "nanobit", "facs"})
_INTERNAL_QUOTE = re.compile(r"(?<![\w'’′])([A-Za-z]+)['’]([A-Za-z]+)(?![\w'’′])")


def _assay_context_allowed(text):
    declarations, issues = context_values(text, partial=True)
    return not issues and not any(
        value is not None for field, value in declarations.items() if field != "assay"
    )


def assay_word_typography(text):
    """Project one spurious internal apostrophe only in a closed known word.

    Original text/provenance stays unchanged. This is a header/assay comparison
    policy, not permission for generic OCR recovery or a model to replace text.
    Prime marks, multiple quotes, unknown words and any letter/digit difference
    remain literal. Distinct technologies are never collapsed.
    """
    if not _assay_context_allowed(text):
        # A known word inside an explicitly named target/construct/condition is
        # still that literal scientific identity, not an assay technology alias.
        return text
    return _INTERNAL_QUOTE.sub(
        lambda match: (
            "".join(match.groups())
            if "".join(match.groups()).casefold() in _ASSAY_WORDS
            else match.group()
        ),
        text,
    )


def assay_header_comparison(fragment, header):
    """Scope fragment typography to a complete metric header, never raw text.

    Either operand's explicit non-assay identity disables projection for BOTH.
    Callers must already own an assay header; a bare label cannot grant it.
    The original packets and all non-assay characters remain unchanged.
    """
    if (
        not METRIC.search(normalize_metric_text(header))
        or not _assay_context_allowed(fragment)
        or not _assay_context_allowed(header)
    ):
        return fragment, header
    return assay_word_typography(fragment), assay_word_typography(header)
