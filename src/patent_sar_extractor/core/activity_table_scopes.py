"""Recompute physical source families from original layouts; saved flags are not proof."""

from dataclasses import asdict

from .activity_continuation_policy import (
    canonical_header,
    caption_prefix,
    compatible_columns,
    continuation_prefix,
)
from .activity_headers import context_from_text, grid_schema
from .activity_table_layout import validate_layout
from .biology_tables import biology_grid_schema


def _anchor(layout):
    origin = layout["header_origin"]
    return (origin["page_no"], tuple(origin["bbox"])) if origin else None


def _root(record):
    layout = record.get("layout")
    if not layout or not layout["header_origin"] or not layout["data_start"]:
        return False
    xs, ys = layout["xs"], layout["ys"]
    expected = (record["page_no"], (xs[0], ys[0], xs[-1], ys[layout["data_start"]]))
    context = context_from_text(layout["prefix"], layout["prefix"])
    schema = biology_grid_schema(grid_schema(context, [layout["raw_headers"]]))
    columns = (
        [
            [
                g.id_column,
                list(map(list, g.value_columns)),
                list(map(list, g.metadata_columns)),
            ]
            for g in schema.groups
        ]
        if schema
        else None
    )
    return (
        _anchor(layout) == expected
        and layout["columns"] == columns
        and schema is not None
        and not schema.needs_review
        and layout["semantic_kind"] == schema.semantic_kind
        and layout["value_kinds"] == list(map(list, schema.value_kinds))
        and layout["context"] == asdict(schema.context)
    )


def _edge(parent, current, root):
    a, b, first = parent["layout"], current["layout"], root["layout"]
    if (
        b["context"] != first["context"]
        or b["semantic_kind"] != first["semantic_kind"]
        or b["value_kinds"] != first["value_kinds"]
        or b["columns"] != first["columns"]
        or (
            b["raw_headers"]
            and tuple(map(canonical_header, b["raw_headers"]))
            != tuple(map(canonical_header, first["raw_headers"]))
        )
    ):
        return False
    same_page = (
        parent["page_no"] == current["page_no"]
        and abs(a["ys"][0] - b["ys"][0]) <= 4
        and a["xs"][-1] < b["xs"][0]
        and compatible_columns(a["xs"], b["xs"], relative=True)
        and caption_prefix(b["prefix"], root["table_id"], first["prefix"])
    )
    adjacent = (
        parent["page_no"] + 1 == current["page_no"]
        and b["ys"][0] < 130
        and compatible_columns(a["xs"], b["xs"])
        and continuation_prefix(a["suffix"])
        and (
            continuation_prefix(b["prefix"])
            or caption_prefix(
                b["prefix"],
                root["table_id"],
                first["context"]["raw_caption"],
                continued=True,
            )
        )
    )
    return same_page or adjacent


def table_scope_groups(records):
    """One original header origin plus complete adjacent/parallel paths.

    No edge can point backwards in physical order or cross a page gap/changed
    assay/field/geometry. Different original roots remain independent sources.
    The same bounded scope is used for header-only completeness and references.
    """
    if len(records) > 25000:
        raise ValueError("Original table scope exceeds its bounded region inventory")
    for record in records:
        validate_layout(record)
    families, invalid, anchors = [], [], {}
    for record in sorted(
        records,
        key=lambda r: (r["page_no"], (r["bbox"] or [0, 0])[1], (r["bbox"] or [0])[0]),
    ):
        if not record.get("layout"):
            families.append([record])
            continue
        if _root(record):
            families.append([record])
            anchors.setdefault(_anchor(record["layout"]), []).append(families[-1])
            continue
        options = [
            family
            for family in anchors.get(_anchor(record["layout"]), [])
            if family[0].get("layout")
            and any(_edge(parent, record, family[0]) for parent in family)
        ]
        if len(options) == 1:
            if len(options[0]) >= 128:
                raise ValueError(
                    "Connected original table exceeds its bounded region inventory"
                )
            options[0].append(record)
        else:
            invalid.append(record)
    return families, invalid


def layout_scope_errors(regions):
    grouped = {}
    for region in regions:
        if region.get("layout"):
            key = (region["table_id"].casefold(), _anchor(region["layout"]))
            grouped.setdefault(key, []).append(region)
    errors = []
    for records in grouped.values():
        families, invalid = table_scope_groups(records)
        errors.extend(
            f"Unproved original table continuation p{r['page_no']} ({r['region_id']})."
            for r in invalid
        )
        errors.extend(
            f"Original table header has no connected result rows p{family[0]['page_no']}."
            for family in families
            if any(r["status"] == "header" for r in family)
            and not any(r["status"] == "parsed" and r["row_count"] for r in family)
        )
    return errors
