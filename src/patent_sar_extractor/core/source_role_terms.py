"""One literal role vocabulary, not identifier normalization or role inference.

Consumers keep their own heading/cell/label boundaries. These explicitly known
spellings name the same intermediate role; original text and molecular IDs stay
unchanged. In particular, an I-prefix is never an intermediate declaration.
"""

import re

INTERMEDIATE_CJK = r"(?:中间体|中間体|中間體)"
INTERMEDIATE_SINGULAR = rf"(?:Intermediate|{INTERMEDIATE_CJK})"
INTERMEDIATE_PLURAL = rf"(?:Intermediates|{INTERMEDIATE_CJK})"
INTERMEDIATE_TERM = rf"(?:Intermediates?|{INTERMEDIATE_CJK})"
# Catalogue-role words only: these do not extend molecular-ID heading grammar.
CATALOG_COMPOUND_CJK = r"(?:化合物|实施例|實施例|実施例|终产物|終產物|最終生成物)"

_KIND = re.compile(INTERMEDIATE_TERM, re.IGNORECASE)
_CASE_BOUNDARY = re.compile(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def role_words(text: str) -> str:
    """Expose literal case boundaries for roles; do not repair source characters.

    The shared projection does not extend identifier/measurement grammar or
    segment unknown lower-case strings with a guessed vocabulary. Raw text is
    retained by each existing source owner, never replaced by this projection.
    """
    return _CASE_BOUNDARY.sub(" ", text)


def is_intermediate_kind(value: object) -> bool:
    return bool(isinstance(value, str) and _KIND.fullmatch(value))
