"""Closed assay-word typography, never fuzzy scientific identifier matching."""

import re

# Existing assay vocabulary only. Manufacturer spellings are documented in
# OPERATIONS; no target, endpoint, unit, compound or arbitrary word is corrected.
_ASSAY_WORDS = frozenset({"htrf", "hibit", "nanobit", "facs"})
_INTERNAL_QUOTE = re.compile(r"(?<![\w'’′])([A-Za-z]+)['’]([A-Za-z]+)(?![\w'’′])")


def assay_word_typography(text):
    """Project one spurious internal apostrophe only in a closed known word.

    Original text/provenance stays unchanged. This is a header/assay comparison
    policy, not permission for generic OCR recovery or a model to replace text.
    Prime marks, multiple quotes, unknown words and any letter/digit difference
    remain literal. Distinct technologies are never collapsed.
    """
    return _INTERNAL_QUOTE.sub(
        lambda match: (
            "".join(match.groups())
            if "".join(match.groups()).casefold() in _ASSAY_WORDS
            else match.group()
        ),
        text,
    )
