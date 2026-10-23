"""Bounded literal result-reference sentences, never inferred result records."""

import re
from dataclasses import dataclass

from .source_paragraphs import PARAGRAPH_LOCATOR
from .source_table_markers import TABLE_INDEX, table_marker_identity

MAX_REFERENCES = 2048
MAX_TARGETS_PER_REFERENCE = 128
_SPACE = r"[ \t\r\n]*"
_REPORT = re.compile(
    r"(?:^|(?<=[.!?。；;]))[ \t]*"
    rf"(?:{PARAGRAPH_LOCATOR}[ \t]*)?"
    rf"(?:(?:The{_SPACE})?Results?{_SPACE}(?:(?:are|were){_SPACE})?"
    rf"(?:shown|listed|reported|provided|summari[sz]ed|presented|included){_SPACE}in{_SPACE}"
    r"|(?:结果|数据)(?:见|列于|示于)\s*)"
    r"(?P<targets>[^.!?。]{1,512})(?:\.(?![A-Za-z0-9])|[!?。]|\Z)",
    re.IGNORECASE | re.MULTILINE,
)
_PREFIX = re.compile(
    r"(?P<word>Tab[li1]es?(?=\s)|Tab[li1]e(?=\d)|表)(?P<space>\s*)",
    re.IGNORECASE,
)
_IDENTIFIER = re.compile(
    rf"(?P<id>{TABLE_INDEX}|[A-Za-z])(?=\s|[,，、;；]|and|以及|和|及|\Z)",
    re.IGNORECASE,
)
_SEPARATOR = re.compile(
    r"(?:[,，、;；]\s*(?:and\s*)?|and\s*|以及\s*|和\s*|及\s*)", re.IGNORECASE
)


@dataclass(frozen=True)
class ResultReference:
    start: int
    end: int
    raw_text: str
    targets: tuple[str, ...]


def _targets(text):
    text = text.strip()
    marker = _PREFIX.match(text)
    if marker is None:
        return ()
    position, output = marker.end(), []
    while True:
        identity = _IDENTIFIER.match(text, position)
        if identity is None:
            return ()
        number = identity["id"]
        if marker["word"].lower().endswith("s") and re.search(r"\d[-–—]\d", number):
            return ()  # Plural dash syntax can be a range or an atomic ID.
        target = (
            "Table " + number
            if marker["word"] != "表"
            else table_marker_identity("表" + marker["space"] + number)
        )
        output.append(target)
        if len(output) > MAX_TARGETS_PER_REFERENCE:
            raise ValueError("Original result reference exceeds its target budget")
        position = identity.end()
        while position < len(text) and text[position].isspace():
            position += 1
        if position == len(text):
            return tuple(dict.fromkeys(output))
        separator = _SEPARATOR.match(text, position)
        if separator is None:
            return ()
        position = separator.end()
        repeated = _PREFIX.match(text, position)
        if repeated is not None:
            marker, position = repeated, repeated.end()


def result_reference_sentences(text):
    """Unknown syntax keeps a nominated span but never a partial target list."""
    if not isinstance(text, str) or len(text) > 100000:
        raise ValueError("Original result-reference source exceeds its text budget")
    output = []
    for match in _REPORT.finditer(text):
        if len(output) >= MAX_REFERENCES:
            raise ValueError("Original result reference exceeds its sentence budget")
        output.append(
            ResultReference(
                match.start(), match.end(), match.group(), _targets(match["targets"])
            )
        )
    return output
