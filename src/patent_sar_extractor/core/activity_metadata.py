"""Literal auxiliary-column evidence; never potency or inferred repeats."""

from __future__ import annotations

import re
import unicodedata

from .activity_values import is_explicit_missing_activity_value

_HEADERS = {
    "n": "reported_n",
    "sample size": "sample_count",
    "number of samples": "sample_count",
    "样本数": "sample_count",
    "样本量": "sample_count",
    "replicates": "replicate_count",
    "number of replicates": "replicate_count",
    "no. of replicates": "replicate_count",
    "重复次数": "replicate_count",
    "重复数": "replicate_count",
}
METADATA_KINDS = frozenset(_HEADERS.values())


def metadata_role(header: object) -> str:
    """Only a complete literal header is known; nM/n(%)/unknown signals are not.

    Bare n remains an unspecified original parameter: no sample-count or Hill
    interpretation is inferred. Counts cannot establish independent replicates.
    Original spelling/value remains evidence, not the potency measurement map.
    """
    if not isinstance(header, str) or len(header) > 4096:
        return ""
    normalized = " ".join(unicodedata.normalize("NFKC", header).split()).casefold()
    return _HEADERS.get(normalized, "")


def metadata_field(kind: str) -> str:
    if kind not in METADATA_KINDS:
        raise ValueError("Unknown original count-column role")
    return f"metadata:{kind}"


def metadata_value_status(value: str, kind: str = "sample_count") -> str:
    if not isinstance(value, str) or len(value) > 1000:
        raise ValueError("Malformed original count value")
    if not value.strip() or is_explicit_missing_activity_value(value):
        return "missing"
    if kind == "reported_n" and re.fullmatch(
        r"[-+]?\d+(?:\.\d+)?(?:[Ee][-+]?\d+)?", value.strip()
    ):
        return "observed"
    if re.fullmatch(r"[1-9]\d{0,8}", value.strip()):
        return "observed"
    return "unresolved"


def metadata_reading_status(cell: dict) -> str:
    kind = metadata_role(cell.get("raw_header"))
    status = metadata_value_status(cell.get("value"), kind)
    observations = cell.get("observations", [])
    if not isinstance(observations, list) or len(observations) > 20:
        raise ValueError("Malformed original count observations")
    values, proved = set(), False
    for observation in observations:
        if not isinstance(observation, dict):
            raise TypeError("Malformed original count observation")
        raw = observation.get("text", "")
        if not isinstance(raw, str) or len(raw) > 10000:
            raise ValueError("Original count observation exceeds its bound")
        method = observation.get("method")
        confidence = observation.get("confidence")
        clipped = method in {"cell_ocr_400dpi", "cell_ocr_600dpi"}
        empty_clip = clipped and (
            type(confidence) in (int, float)
            and confidence == 0
            and observation.get("ink_crop_pixels", "unobserved") is None
            and observation.get("raw_text") == ""
            and observation.get("parts") == []
        )
        qualified = (
            method in {"native_cell", "declared_text_count_cell"}
            or (
                clipped and type(confidence) in (int, float) and 0.85 <= confidence <= 1
            )
            or empty_clip
        )
        if clipped and not qualified:
            continue
        if (
            method
            in {
                "native_cell",
                "page_ocr_cell",
                "cell_ocr_400dpi",
                "cell_ocr_600dpi",
                "declared_text_count_cell",
            }
            and metadata_value_status(raw, kind) != "unresolved"
        ):
            if not raw.strip() and clipped and not empty_clip:
                continue
            key = (
                "missing"
                if metadata_value_status(raw, kind) == "missing"
                else raw.strip()
            )
            values.add(key)
            proved |= qualified
    expected = "missing" if status == "missing" else cell["value"].strip()
    if not proved or len(values) != 1 or expected not in values:
        return "unresolved"
    return status


def mark_metadata(cell: dict, kind: str) -> dict:
    if metadata_role(cell.get("raw_header")) != kind:
        raise ValueError("Original header does not prove its count-column role")
    return {
        **cell,
        "field": metadata_field(kind),
        "role": "metadata",
        "metadata_kind": kind,
        "metadata_status": metadata_reading_status(cell),
    }


def metadata_cell(cell: dict) -> bool:
    """Recheck persisted proof; a metadata marker cannot hide a measurement."""
    field = cell.get("field", "")
    if not isinstance(field, str):
        raise TypeError("Malformed original field identity")
    declared = cell.get("role") == "metadata"
    if not declared and not field.startswith("metadata:"):
        if "metadata_kind" in cell or "metadata_status" in cell:
            raise ValueError("Count evidence has no declared column role")
        return False
    kind = cell.get("metadata_kind")
    if (
        not declared
        or kind not in METADATA_KINDS
        or field != metadata_field(kind)
        or metadata_role(cell.get("raw_header")) != kind
        or type(cell.get("physical_column")) is not int
        or not 0 <= cell["physical_column"] < 500
        or cell.get("metadata_status") != metadata_reading_status(cell)
    ):
        raise ValueError("Unproved original count-column evidence")
    return True


def metadata_evidence_errors(rows: list[dict]) -> list[str]:
    if not isinstance(rows, list) or len(rows) > 25000:
        raise ValueError("Original count rows exceed their bound")
    errors = []
    for row in rows:
        used, unresolved = 0, False
        sources = row.get("activity_sources", [])
        if not isinstance(sources, list) or len(sources) > 500:
            raise ValueError("Malformed original count sources")
        for source in sources:
            if not isinstance(source, dict):
                raise TypeError("Malformed original count source")
            cells = source.get("cells", [])
            if not isinstance(cells, list) or len(cells) > 500:
                raise ValueError("Malformed original count cells")
            used += len(cells)
            if used > 2000:
                raise ValueError("Original row count evidence exceeds its bound")
            for cell in cells:
                if not isinstance(cell, dict):
                    raise TypeError("Malformed original count cell")
                if metadata_cell(cell) and cell["metadata_status"] == "unresolved":
                    unresolved = True
        if unresolved:
            errors.append(f"Original count requires review: {row.get('cpd', '')}.")
    return errors
