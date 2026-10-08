"""Bounded original-source inventory, independent of rows and optional API use."""

from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any

from patent_sar_extractor.contracts import (
    ACTIVITY_COVERAGE_SCHEMA,
    ACTIVITY_COVERAGE_SCHEMA_VERSION,
    schema_ref,
)

MAX_REGIONS = 25000
STATUSES = {"parsed", "empty", "unresolved"}
KINDS = {"grid", "text", "page"}
REASONS = {
    "original_cells",
    "declared_text",
    "unsupported_header",
    "no_original_rows",
    "no_supported_activity_table",
    "empty_original_cells",
}


def source_record(
    page_no: int,
    kind: str,
    bbox: list[float] | None,
    table_id: str,
    header: str,
    status: str,
    reason: str,
    row_count: int,
) -> dict[str, Any]:
    record = {
        "page_no": page_no,
        "kind": kind,
        "bbox": bbox,
        "table_id": table_id[:256],
        "header": header[:1024],
        "status": status,
        "reason": reason,
        "row_count": row_count,
    }
    identity = [page_no, kind, bbox, record["table_id"], record["header"]]
    record["region_id"] = hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()[:32]
    _validate_region(record)
    return record


def _validate_region(record: dict) -> None:
    if (
        not isinstance(record, dict)
        or set(record)
        != {
            "region_id",
            "page_no",
            "kind",
            "bbox",
            "table_id",
            "header",
            "status",
            "reason",
            "row_count",
        }
        or not isinstance(record["region_id"], str)
        or not re.fullmatch(r"[a-f0-9]{32}", record["region_id"])
        or type(record["page_no"]) is not int
        or not 1 <= record["page_no"] <= 10000
        or record["kind"] not in KINDS
        or record["status"] not in STATUSES
        or record["reason"] not in REASONS
        or type(record["row_count"]) is not int
        or not 0 <= record["row_count"] <= 25000
        or any(
            not isinstance(record[key], str) or len(record[key]) > limit
            for key, limit in (("table_id", 256), ("header", 1024))
        )
        or record["status"] == "parsed"
        and record["row_count"] == 0
        or record["status"] != "parsed"
        and record["row_count"] != 0
    ):
        raise ValueError("Malformed activity source inventory")
    bbox = record["bbox"]
    if bbox is not None and (
        not isinstance(bbox, list)
        or len(bbox) != 4
        or any(
            type(value) not in (int, float)
            or not math.isfinite(value)
            or not 0 <= value <= 100000
            for value in bbox
        )
        or bbox[0] >= bbox[2]
        or bbox[1] >= bbox[3]
    ):
        raise ValueError("Malformed activity source geometry")
    identity = [
        record["page_no"],
        record["kind"],
        bbox,
        record["table_id"],
        record["header"],
    ]
    expected = hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()[:32]
    if record["region_id"] != expected:
        raise ValueError(
            "Activity source identity does not match its original observation"
        )


def coverage_packet(seed_pages: list[int], regions: list[dict], rows: list) -> dict:
    """A missing seed cannot become success merely because another page has rows."""
    if not isinstance(seed_pages, list) or any(
        type(page) is not int or not 0 <= page < 10000 for page in seed_pages
    ):
        raise ValueError("Malformed activity source seeds")
    seeds = sorted(set(seed_pages))
    observed = {region["page_no"] for region in regions}
    records = list(regions)
    parsed_pages = {
        region["page_no"] for region in records if region["status"] == "parsed"
    }
    if any(row.page_no not in parsed_pages for row in rows):
        raise ValueError("An activity row has no recorded parsed original source")
    for page in seeds:
        if page + 1 not in observed:
            records.append(
                source_record(
                    page + 1,
                    "page",
                    None,
                    "",
                    "",
                    "unresolved",
                    "no_supported_activity_table",
                    0,
                )
            )
    packet = {
        "schema": schema_ref(
            ACTIVITY_COVERAGE_SCHEMA, ACTIVITY_COVERAGE_SCHEMA_VERSION
        ),
        "seed_pages": seeds,
        "regions": records,
    }
    coverage_errors(packet, seeds)
    return packet


def coverage_errors(packet: object, seed_pages: list[int] | None) -> list[str]:
    if packet is None:
        return [
            "Activity source coverage proof is missing; a fresh activity extraction is required."
        ]
    if (
        not isinstance(packet, dict)
        or set(packet) != {"schema", "seed_pages", "regions"}
        or packet["schema"]
        != schema_ref(ACTIVITY_COVERAGE_SCHEMA, ACTIVITY_COVERAGE_SCHEMA_VERSION)
        or not isinstance(packet["seed_pages"], list)
        or any(
            type(page) is not int or not 0 <= page < 10000
            for page in packet["seed_pages"]
        )
        or packet["seed_pages"] != sorted(set(packet["seed_pages"]))
        or seed_pages is not None
        and packet["seed_pages"] != sorted(set(seed_pages))
        or not isinstance(packet["regions"], list)
        or len(packet["regions"]) > MAX_REGIONS
    ):
        raise ValueError("Malformed or foreign activity coverage proof")
    seen, pages, errors = set(), set(), []
    for region in packet["regions"]:
        _validate_region(region)
        if region["region_id"] in seen:
            raise ValueError("Duplicate activity source region")
        seen.add(region["region_id"])
        pages.add(region["page_no"])
        if region["status"] == "unresolved":
            errors.append(
                f"Unresolved activity source p{region['page_no']} ({region['reason']}, {region['region_id']})."
            )
    if any(page + 1 not in pages for page in packet["seed_pages"]):
        raise ValueError("Activity seed page is absent from its coverage proof")
    return errors
