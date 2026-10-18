"""One exact source-caption grammar; annotations never assign stereochemistry."""

import re

from .printed_identifiers import (
    LABEL_PREFIX,
    PRINTED_ID,
    identifier_text,
    label_kind_namespace,
)

_CAPTION = re.compile(
    rf"(?P<identity>{LABEL_PREFIX}(?P<number>{PRINTED_ID}))"
    r"(?:\s*\*?\s*(?:first|second)\s*eluting\s*isomer)?",
    re.IGNORECASE,
)


def caption_identity(value: str) -> tuple[str, int]:
    """Return printed ID and identity span in whitespace-compacted source text.

    The whole caption must match. Other numbers, unknown annotations and synthesis
    prose cannot be dropped. Literal elution notes remain raw evidence only.
    """
    text = identifier_text(value)
    match = _CAPTION.fullmatch(text)
    return (
        (
            match.group("number").upper(),
            len(re.sub(r"\s+", "", text[: match.end("identity")])),
        )
        if match
        else ("", 0)
    )


def prefixed_label(value: str) -> str:
    return caption_identity(value)[0]


def caption_namespace(value: str) -> str:
    """Use the same whole-caption grammar, including literal elution annotations."""
    text = identifier_text(value)
    match = _CAPTION.fullmatch(text)
    if match is None:
        return ""
    kind = re.sub(r"[\s:：.\-]", "", text[: match.start("number")])
    return label_kind_namespace(kind)
