"""Validate declared metadata without trusting it as scientific evidence."""

from __future__ import annotations

import re

from .errors import WebError

_IDENTIFIER = re.compile(r"[A-Z][A-Z0-9._-]{0,63}\Z")


def patent_identifier(value: str) -> str:
    normalized = value.strip().upper()
    if normalized.startswith("WO"):
        normalized = normalized.replace("/", "")
    if not _IDENTIFIER.fullmatch(normalized):
        raise WebError(
            400,
            "invalid_patent_id",
            "Patent identifier must be a bounded identifier, not a path or command.",
        )
    return normalized
