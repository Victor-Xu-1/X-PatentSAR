"""One bounded, literal identifier grammar; no sequence or OCR-digit repair."""

import re

_SERIES_HEAD = r"[A-Za-zＡ-Ｚａ-ｚ]{1,12}"
_ID_NUMBER = r"[0-9０-９]{1,8}(?:[-－][0-9０-９]{1,8})*"
_ID_LETTERS = r"[A-Za-zＡ-Ｚａ-ｚ]"
_ID_BODY = rf"{_ID_NUMBER}(?:[-－]?{_ID_LETTERS}{{1,4}})?"
# Full identities are read only in a source role/cell or after an explicit label.
# Unqualified prose locators keep the narrower shape; a hash or endpoint token
# cannot nominate a compound merely because it is syntactically alphanumeric.
PRINTED_ID = rf"(?:{_SERIES_HEAD}[-－]?)?{_ID_BODY}"
LOCATOR_ID = rf"(?:{_SERIES_HEAD}[-－])?{_ID_NUMBER}{_ID_LETTERS}{{0,4}}"
LABEL_KIND = r"(?:Compound|Cmpd|Cpd|Example|实施例|化合物)"
LABEL_PREFIX = rf"{LABEL_KIND}\s*[-:.：]?\s*"
_BARE = re.compile(PRINTED_ID, re.IGNORECASE)
_WRAPPED = re.compile(rf"(?:{LABEL_PREFIX})?({PRINTED_ID})", re.IGNORECASE)
_TOKEN = re.compile(rf"(?<![\w./-]){PRINTED_ID}(?![\w./-])", re.IGNORECASE)
_PREFIX = re.compile(rf"^{LABEL_PREFIX}", re.IGNORECASE)
_WIDTH = str.maketrans(
    "０１２３４５６７８９ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ－",
    "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-",
)


def identifier_width(value: str) -> str:
    return value.translate(_WIDTH)


def identifier_text(value: object) -> str:
    text = str(value or "")
    return identifier_width(text).strip() if len(text) <= 128 else ""


def identifier_key(value: object, *, wrapped=False, terminal_period=False) -> str:
    """Normalize only case/printed width/wrapper, preserving zeros and all tokens.

    Spaces inside an identifier never join digits or suffixes. A terminal row
    punctuation mark is permitted only by explicit source-cell callers. Fullwidth
    glyphs have one-to-one typography equivalents; superscripts and OCR-confusable
    letters/digits are not replaced. Original raw text remains source evidence.
    """
    text = identifier_text(value)
    if terminal_period:
        text = text.removesuffix(".")
    match = (_WRAPPED if wrapped else _BARE).fullmatch(text)
    return (match.group(1) if wrapped else match.group()).upper() if match else ""


def identifier_fragments_conflict(value: str, expected: str, *, caption=False) -> bool:
    """Unparsed original ID fragments cannot be outvoted by agreeing rereads."""
    text = identifier_text(value)
    if not text:
        return bool(value.strip())
    whole = identifier_key(text, wrapped=True, terminal_period=True)
    if whole:
        return whole != expected
    if caption and _PREFIX.match(text):
        return True  # Unsupported annotation/prose after a known caption prefix.
    if any(char.isnumeric() and not char.isdecimal() for char in text):
        return True  # Superscripts/footnotes are not new identifier digits.
    keys = {identifier_key(match.group()) for match in _TOKEN.finditer(text)}
    return bool(keys and keys != {expected})
