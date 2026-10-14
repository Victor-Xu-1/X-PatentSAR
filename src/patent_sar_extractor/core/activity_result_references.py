"""Bounded literal result links; no value parser, condition inference or recursion."""

from __future__ import annotations

import math
import re
from collections import defaultdict

from .activity_identity import is_value, normalize_compound, normalize_value
from .activity_metadata import metadata_role
from .activity_source_roles import method_result_references
from .activity_table_scopes import table_scope_groups
from .cell_cross_observation import printed_cross_valid
from .source_table_markers import TABLE_MARKER, table_marker_identity

MAX_REFERENCES = 2048
MAX_TARGETS_PER_REFERENCE = 128
MAX_REFERENCE_TARGETS = 8192
MAX_SOURCE_PACKETS = 100000


def _get(row, key, default=None):
    return (
        row.get(key, default) if isinstance(row, dict) else getattr(row, key, default)
    )


def _key(table):
    return re.sub(r"\s+", " ", str(table)).strip().casefold()


def _caption_key(text):
    if not isinstance(text, str) or len(text) > 10000:
        return ""
    caption = re.sub(r"^\[\d{4,8}\]\s*", "", text.strip())
    markers = list(TABLE_MARKER.finditer(caption))
    if len(markers) != 1 or markers[0].start() != 0:
        return ""
    return _key(table_marker_identity(markers[0].group()))


def _inside(cell, outer):
    return (
        isinstance(cell, (list, tuple))
        and len(cell) == 4
        and all(type(x) in (int, float) and math.isfinite(x) for x in cell)
        and outer[0] <= cell[0] < cell[2] <= outer[2]
        and outer[1] <= cell[1] < cell[3] <= outer[3]
    )


def _observed(cell, identifier=False):
    """Re-use exact literal normalization; a boolean cannot outvote readings."""
    readings = cell.get("observations")
    if not isinstance(readings, list) or not 1 <= len(readings) <= 64:
        return False
    normalize = normalize_compound if identifier else normalize_value
    cross = not identifier and any(
        printed_cross_valid(o, cell.get("bbox"), cell.get("value")) for o in readings
    )
    values, proved = set(), False
    for item in readings:
        if not isinstance(item, dict) or not isinstance(item.get("text"), str):
            return False
        method, confidence = item.get("method"), item.get("confidence")
        if method == "printed_cross_components":
            if not printed_cross_valid(item, cell.get("bbox"), cell.get("value")):
                return False
            values.add(normalize(item["text"]))
            proved = True
            continue
        if (
            cross
            and method == "page_ocr_cell"
            and re.fullmatch(r"\+{1,5}", item["text"])
        ):
            continue  # Locator fragment count is not the whole-cell observation.
        clipped = method in {"cell_ocr_400dpi", "cell_ocr_600dpi"}
        qualified = method in {"native_cell", "declared_text_cell", "declared_text_row"}
        if clipped:
            qualified = (
                type(confidence) in (int, float)
                and 0.85 <= confidence <= 1
                and item.get("bbox") == cell.get("bbox")
                and item.get("coordinate_space") == "original_pdf_points"
            )
            if not qualified:
                continue
        if method not in {
            "native_cell",
            "page_ocr_cell",
            "cell_ocr_400dpi",
            "cell_ocr_600dpi",
            "declared_text_cell",
            "declared_text_row",
        }:
            continue
        if normalize_compound(item["text"]) if identifier else is_value(item["text"]):
            values.add(normalize(item["text"]))
            proved |= qualified
    return proved and values == {normalize(cell.get("value", ""))}


def _original_text_row(source, cells):
    """Re-read a declared row through the same parser, not a parallel grammar."""
    from .activity_text_rows import parse_segment

    raw = {
        observation.get("raw_text")
        for cell in cells
        for observation in cell.get("observations", [])
        if observation.get("method") in {"declared_text_row", "declared_text_cell"}
    }
    if len(raw) != 1:
        return False
    raw_row = raw.pop()
    if not isinstance(raw_row, str) or not raw_row or len(raw_row) > 10000:
        return False
    original = parse_segment(
        source["raw_caption"],
        raw_row,
        page_no=source["page_no"],
        header=source.get("raw_header", ""),
    )
    if len(original) != 1 or original[0].needs_review:
        return False
    fields = original[0].activity_values
    return all(
        normalize_compound(cell["value"]) == original[0].cpd
        if cell["field"] == "compound_id"
        else fields.get(cell["field"]) == cell["value"]
        for cell in cells
        if not cell["field"].startswith("metadata:")
    )


def _source_matches(row, source, region):
    if (
        _get(row, "needs_review", False)
        or not isinstance(source, dict)
        or type(source.get("page_no")) is not int
        or source["page_no"] != region["page_no"]
        or _key(source.get("table_id", "")) != _key(region["table_id"])
        or _caption_key(source.get("raw_caption")) != _key(region["table_id"])
        or type(source.get("row")) is not int
        or source["row"] < 0
        or type(source.get("pair", 0)) is not int
        or source.get("pair", 0) < 0
    ):
        return False
    cells = source.get("cells")
    if (
        not isinstance(cells, list)
        or not 2 <= len(cells) <= 256
        or any(
            not isinstance(cell, dict) or not isinstance(cell.get("field"), str)
            for cell in cells
        )
    ):
        return False
    if region["kind"] == "text" and not _original_text_row(source, cells):
        return False
    if region.get("layout") and source.get("table_bbox") != region["bbox"]:
        return False
    values = {**_get(row, "activity_values", {}), **_get(row, "cell_line_data", {})}
    identifiers, measurements = [], []
    for cell in cells:
        if not isinstance(cell, dict) or not isinstance(cell.get("field"), str):
            return False
        if region["kind"] == "grid":
            if not region["bbox"] or not _inside(cell.get("bbox"), region["bbox"]):
                return False
        elif (
            cell.get("bbox") is not None
            or source.get("raw_header", "")[:1024] != region["header"]
        ):
            return False
        field = cell["field"]
        if field == "compound_id":
            if not _observed(cell, True):
                return False
            identifiers.append(normalize_compound(cell.get("value", "")))
        elif not field.startswith("metadata:"):
            if (
                metadata_role(field)
                or "unknown" in field.lower()
                or values.get(field) != cell.get("value")
                or not _observed(cell)
            ):
                return False
            measurements.append(field)
    return identifiers == [normalize_compound(_get(row, "cpd", ""))] and bool(
        measurements
    )


def result_references(regions, rows):
    """Recompute all links from original region and row evidence on every read.

    A target is one exact physical source family with complete row/cell proof.
    Reused IDs without a connected original header/column/boundary proof stay
    ambiguous, not nearest-page wins.
    Method/reference nodes never qualify as targets, so cycles cannot resolve.
    """
    if not any(region["status"] == "reference" for region in regions):
        return []
    if rows is not None and (not isinstance(rows, list) or len(rows) > 25000):
        raise ValueError("Original reference rows exceed the bounded inventory")
    tables, sources = defaultdict(list), defaultdict(list)
    for region in regions:
        if region["table_id"] and region["kind"] in {"grid", "text"}:
            tables[_key(region["table_id"])].append(region)
    source_count = 0
    for row in rows or []:
        observations = _get(row, "activity_sources", [])
        if not isinstance(observations, list) or len(observations) > 500:
            raise ValueError("Malformed or unbounded original result sources")
        source_count += len(observations)
        if source_count > MAX_SOURCE_PACKETS:
            raise ValueError("Original reference source packets exceed their bound")
        for source in observations:
            if not isinstance(source, dict):
                raise TypeError("Malformed original result source")
            if type(source.get("page_no")) is int:
                sources[(source["page_no"], _key(source.get("table_id", "")))].append(
                    (row, source)
                )
    output, resolved, edge_count = [], {}, 0
    for region in regions:
        if region["status"] != "reference":
            continue
        for table in method_result_references(region["header"]):
            if len(output) >= MAX_REFERENCES:
                raise ValueError(
                    "Original result references exceed the bounded inventory"
                )
            key = _key(table)
            if key not in resolved:
                targets = tables[key]
                if len(targets) > MAX_TARGETS_PER_REFERENCE:
                    raise ValueError(
                        "Original reference target scope exceeds its bound"
                    )
                status = "missing" if not targets else "ambiguous"
                families, invalid = table_scope_groups(targets)
                if len(families) == 1 and not invalid:
                    status = "unproved"
                    proved = any(item["row_count"] for item in families[0])
                    for target in families[0]:
                        if target["status"] == "header":
                            continue
                        observations = [
                            pair
                            for pair in sources[(target["page_no"], key)]
                            if (
                                pair[1].get("table_bbox") == target["bbox"]
                                if target.get("layout")
                                else True
                            )
                        ]
                        positions = [
                            (s.get("row"), s.get("pair", 0)) for _, s in observations
                        ]
                        proved &= bool(
                            target["status"] == "parsed"
                            and len(observations) == target["row_count"]
                            and len(set(positions)) == len(positions)
                            and all(
                                _source_matches(row, source, target)
                                for row, source in observations
                            )
                        )
                    if proved:
                        status = "resolved"
                resolved[key] = status, [item["region_id"] for item in targets]
            status, target_ids = resolved[key]
            edge_count += len(target_ids)
            if edge_count > MAX_REFERENCE_TARGETS:
                raise ValueError("Original reference target edges exceed their bound")
            output.append(
                {
                    "source_region_id": region["region_id"],
                    "table_id": table,
                    "target_region_ids": target_ids,
                    "status": status,
                }
            )
    return output
