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
    schema_ref_matches,
)

from .activity_grid_role_proof import valid_role_scope
from .activity_result_references import result_references
from .activity_source_roles import method_page_evidence, method_result_references
from .activity_table_layout import validate_layout
from .activity_table_rows import table_row_errors
from .activity_table_scopes import layout_scope_errors
from .activity_text_plan import validate_text_pages, validate_text_scope
from .activity_text_proof import text_source_errors

MAX_REGIONS = 25000
STATUSES = {
    "parsed",
    "empty",
    "unresolved",
    "context",
    "reference",
    "header",
    "non_activity",
}
KINDS = {"grid", "text", "page"}
REASONS = {
    "original_cells",
    "declared_text",
    "unsupported_header",
    "no_original_rows",
    "no_supported_activity_table",
    "empty_original_cells",
    "observed_methods",
    "observed_result_references",
    "unsupported_result_reference",
    "conflicting_result_references",
    "original_header_only",
    "observed_characterization",
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
    *,
    layout: dict | None = None,
    text_scope: dict | None = None,
    role_scope: dict | None = None,
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
    if text_scope is not None:
        identity.append(text_scope["span"])
        record["text_scope"] = text_scope
    record["region_id"] = hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()[:32]
    if layout is not None:
        record["layout"] = layout
    if role_scope is not None:
        record["role_scope"] = role_scope
    _validate_region(record)
    return record


def _validate_region(record: dict) -> None:
    if (
        not isinstance(record, dict)
        or set(record) - {"layout", "text_scope", "role_scope"}
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
        or (record["status"] == "context" or record["reason"] == "observed_methods")
        and not (
            record["status"] == "context"
            and record["reason"] == "observed_methods"
            and record["kind"] == "page"
            and record["bbox"] is None
            and not record["table_id"]
            and method_page_evidence(record["header"])
        )
        or (
            record["status"] == "reference"
            or record["reason"] == "observed_result_references"
        )
        and not (
            record["status"] == "reference"
            and record["reason"] == "observed_result_references"
            and record["kind"] == "page"
            and record["bbox"] is None
            and not record["table_id"]
            and method_result_references(record["header"])
        )
        or record["reason"]
        in {"unsupported_result_reference", "conflicting_result_references"}
        and not (
            record["status"] == "unresolved"
            and record["kind"] == "page"
            and record["bbox"] is None
            and not record["table_id"]
        )
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
    if "text_scope" in record:
        validate_text_scope(record)
        identity.append(record["text_scope"]["span"])
    expected = hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()[:32]
    if record["region_id"] != expected:
        raise ValueError(
            "Activity source identity does not match its original observation"
        )
    validate_layout(record)
    if (
        record["status"] == "non_activity"
        or record["reason"] == "observed_characterization"
        or "role_scope" in record
    ) and not (
        record["status"] == "non_activity"
        and record["reason"] == "observed_characterization"
        and record["kind"] == "grid"
        and bbox is not None
        and "layout" not in record
        and "text_scope" not in record
        and valid_role_scope(record)
    ):
        raise ValueError("Unproved original characterization grid role")
    if (
        record["status"] == "header" or record["reason"] == "original_header_only"
    ) and not (
        record["status"] == "header"
        and record["reason"] == "original_header_only"
        and (
            record["kind"] == "grid"
            and record.get("layout")
            and record["layout"]["data_start"] == len(record["layout"]["ys"]) - 1
            or record["kind"] == "text"
            and record.get("text_scope")
            and record["header"]
        )
    ):
        raise ValueError("Malformed original header-only source")


def coverage_packet(
    seed_pages: list[int],
    regions: list[dict],
    rows: list,
    *,
    discovered_pages: list[int] | None = None,
    text_pages: dict[str, str] | None = None,
) -> dict:
    """A missing seed cannot become success merely because another page has rows."""
    if not isinstance(seed_pages, list) or any(
        type(page) is not int or not 0 <= page < 10000 for page in seed_pages
    ):
        raise ValueError("Malformed activity source seeds")
    seeds = sorted(set(seed_pages))
    if discovered_pages is not None and (
        not isinstance(discovered_pages, list)
        or any(
            type(page) is not int or not 0 <= page < 10000 for page in discovered_pages
        )
    ):
        raise ValueError("Malformed discovered activity source pages")
    discovered = sorted(set(discovered_pages or []))
    observed = {
        region["page_no"] for region in regions if region["status"] != "non_activity"
    }
    records = list(regions)
    parsed_pages = {
        region["page_no"] for region in records if region["status"] == "parsed"
    }
    if any(row.page_no not in parsed_pages for row in rows):
        raise ValueError("An activity row has no recorded parsed original source")
    for page in sorted(set(seeds) | set(discovered)):
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
        "discovered_pages": discovered,
        "regions": records,
        "references": result_references(records, rows),
        "text_pages": text_pages or {},
    }
    coverage_errors(packet, seeds, rows=rows)
    return packet


def coverage_errors(
    packet: object, seed_pages: list[int] | None, *, rows=None
) -> list[str]:
    if packet is None:
        return [
            "Activity source coverage proof is missing; a fresh activity extraction is required."
        ]
    if (
        not isinstance(packet, dict)
        or set(packet)
        != {
            "schema",
            "seed_pages",
            "discovered_pages",
            "regions",
            "references",
            "text_pages",
        }
        or not schema_ref_matches(
            packet["schema"],
            schema_ref(ACTIVITY_COVERAGE_SCHEMA, ACTIVITY_COVERAGE_SCHEMA_VERSION),
        )
        or not isinstance(packet["seed_pages"], list)
        or any(
            type(page) is not int or not 0 <= page < 10000
            for page in packet["seed_pages"]
        )
        or packet["seed_pages"] != sorted(set(packet["seed_pages"]))
        or not isinstance(packet["discovered_pages"], list)
        or any(
            type(page) is not int or not 0 <= page < 10000
            for page in packet["discovered_pages"]
        )
        or packet["discovered_pages"] != sorted(set(packet["discovered_pages"]))
        or seed_pages is not None
        and packet["seed_pages"] != sorted(set(seed_pages))
        or not isinstance(packet["regions"], list)
        or len(packet["regions"]) > MAX_REGIONS
        or not isinstance(packet["references"], list)
        or len(packet["references"]) > 2048
    ):
        raise ValueError("Malformed or foreign activity coverage proof")
    validate_text_pages(packet["text_pages"])
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
    if any(
        page + 1 not in pages
        for page in set(packet["seed_pages"]) | set(packet["discovered_pages"])
    ):
        raise ValueError("Activity seed page is absent from its coverage proof")
    errors.extend(layout_scope_errors(packet["regions"]))
    errors.extend(table_row_errors(packet["regions"], rows))
    errors.extend(text_source_errors(packet["text_pages"], packet["regions"], rows))
    if packet["references"] and rows is None:
        errors.append(
            "Original result references require their current source rows for validation."
        )
    else:
        references = result_references(packet["regions"], rows)
        if references != packet["references"]:
            raise ValueError(
                "Result-reference links do not match the original regions and cells"
            )
        errors.extend(
            f"Unresolved original result reference {ref['table_id']} ({ref['status']}, {ref['source_region_id']})."
            for ref in references
            if ref["status"] != "resolved"
        )
    return errors
