"""Bounded original-source inventory, independent of rows and optional API use."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from patent_sar_extractor.contracts import (
    ACTIVITY_COVERAGE_SCHEMA,
    ACTIVITY_COVERAGE_SCHEMA_VERSION,
    schema_ref,
    schema_ref_matches,
)

from .activity_context_geometry import validate_context_inventory
from .activity_region_proof import validate_region
from .activity_result_references import result_references
from .activity_table_rows import table_row_errors
from .activity_table_scopes import layout_scope_errors
from .activity_text_plan import validate_text_pages
from .activity_text_proof import text_source_errors
from .activity_transposed_rows import transposed_row_errors

MAX_REGIONS = 25000


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
    grid_axes: dict | None = None,
    parent_grid: list | None = None,
    column_scope: dict | None = None,
    transposed_layout: dict | None = None,
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
    if parent_grid is not None:
        identity.append(parent_grid)
        record["parent_grid"] = parent_grid
    for key, value in (
        ("column_scope", column_scope),
        ("transposed_layout", transposed_layout),
    ):
        if value is not None:
            identity.append(value)
            record[key] = value
    record["region_id"] = hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()[:32]
    if layout is not None:
        record["layout"] = layout
    if role_scope is not None:
        record["role_scope"] = role_scope
    if grid_axes is not None:
        record["grid_axes"] = grid_axes
    validate_region(record)
    return record


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
        validate_region(region)
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
    validate_context_inventory(
        packet["regions"],
        current=schema_ref_matches(
            packet["schema"],
            schema_ref(ACTIVITY_COVERAGE_SCHEMA, ACTIVITY_COVERAGE_SCHEMA_VERSION),
        ),
    )
    errors.extend(layout_scope_errors(packet["regions"]))
    errors.extend(table_row_errors(packet["regions"], rows))
    errors.extend(transposed_row_errors(packet["regions"], rows))
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
