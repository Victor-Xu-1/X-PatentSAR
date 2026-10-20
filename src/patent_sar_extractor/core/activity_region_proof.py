"""Original activity region shape, identity and role validation; no row writer."""

from __future__ import annotations

import hashlib
import json
import math
import re

from .activity_context_geometry import validate_grid_axes
from .activity_grid_role_proof import valid_role_scope
from .activity_source_roles import method_page_evidence, method_result_references
from .activity_table_layout import validate_layout
from .activity_text_plan import validate_text_scope
from .activity_transposed_source import (
    validate_column_scope,
    validate_transposed_layout,
)

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


def validate_region(record: dict) -> None:
    if (
        not isinstance(record, dict)
        or set(record)
        - {
            "layout",
            "text_scope",
            "role_scope",
            "grid_axes",
            "parent_grid",
            "column_scope",
            "transposed_layout",
        }
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
    if "parent_grid" in record:
        parent = record["parent_grid"]
        if (
            record["kind"] != "grid"
            or record["status"] != "unresolved"
            or record["reason"] != "no_original_rows"
            or any(
                key in record
                for key in (
                    "layout",
                    "grid_axes",
                    "role_scope",
                    "text_scope",
                    "column_scope",
                    "transposed_layout",
                )
            )
            or not isinstance(parent, list)
            or len(parent) != 4
            or any(type(v) not in {int, float} or not math.isfinite(v) for v in parent)
            or bbox is None
            or not 0 <= parent[0] <= bbox[0] < bbox[2] <= parent[2] <= 100000
            or not 0 <= parent[1] <= bbox[1] < bbox[3] <= parent[3] <= 100000
        ):
            raise ValueError("Malformed unresolved original row parent")
        identity.append(parent)
    validate_column_scope(record)
    validate_transposed_layout(record)
    for key in ("column_scope", "transposed_layout"):
        if key in record:
            identity.append(record[key])
    expected = hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()[:32]
    if record["region_id"] != expected:
        raise ValueError(
            "Activity source identity does not match its original observation"
        )
    validate_layout(record)
    if "grid_axes" in record:
        if record["kind"] != "grid":
            raise ValueError("Original physical axes belong only to grids")
        validate_grid_axes(record["grid_axes"], bbox)
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
