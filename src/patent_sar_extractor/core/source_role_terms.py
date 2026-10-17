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


def is_intermediate_kind(value: object) -> bool:
    return bool(isinstance(value, str) and _KIND.fullmatch(value))
