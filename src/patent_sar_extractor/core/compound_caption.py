"""One exact source-caption grammar; annotations never assign stereochemistry."""

import re

_CAPTION = re.compile(
    r"(?P<identity>(?:Example|Compound|Cmpd|Cpd|实施例|化合物)[-:.]?"
    r"(?P<number>[1-9]\d{0,3}[A-Z]?))"
    r"(?:\*?(?:first|second)elutingisomer)?",
    re.IGNORECASE,
)


def caption_identity(value: str) -> tuple[str, int]:
    """Return printed ID and identity span in whitespace-compacted source text.

    The whole caption must match. Other numbers, unknown annotations and synthesis
    prose cannot be dropped. Literal elution notes remain raw evidence only.
    """
    compact = re.sub(r"\s+", "", value)
    match = _CAPTION.fullmatch(compact)
    return (match.group("number").upper(), match.end("identity")) if match else ("", 0)


def prefixed_label(value: str) -> str:
    return caption_identity(value)[0]
