"""HTTP error boundary around the shared original-ID/crop ownership reader."""

from __future__ import annotations

from typing import Any

from patent_sar_extractor.core.catalog_reader import read_catalog_entries

from .errors import WebError


def read_compound_catalog(
    payload: dict[str, Any], structures: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]] | None, set[str]]:
    try:
        return read_catalog_entries(
            payload, {str(item.get("structure_id") or "") for item in structures}
        )
    except ValueError as exc:
        raise WebError(422, "invalid_compound_catalog", str(exc)) from exc
