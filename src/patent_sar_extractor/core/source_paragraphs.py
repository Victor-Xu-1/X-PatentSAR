"""Literal paragraph metadata, independent of molecular or assay identity.

Only paired printed brackets and a bounded decimal locator are recognized.
Callers still own heading/line boundaries and retain their complete raw source.
No malformed bracket, compound label, value or source character is repaired.
"""

import re

PARAGRAPH_LOCATOR = r"(?:\[\s*\d{1,8}\s*\]|［\s*\d{1,8}\s*］)"
_PREFIX = re.compile(rf"^[ \t]*(?:{PARAGRAPH_LOCATOR})[ \t]*")
_ONLY = re.compile(rf"(?:{PARAGRAPH_LOCATOR})")


def strip_paragraph_locator(text: str) -> str:
    """Return the literal suffix for comparison, never replace the raw carrier."""
    match = _PREFIX.match(text)
    return text[match.end() :] if match else text


def paragraph_only(text: str) -> bool:
    return _ONLY.fullmatch(text.strip()) is not None
