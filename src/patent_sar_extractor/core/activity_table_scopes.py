"""Recompute physical source families from original layouts; saved flags are not proof."""

from dataclasses import asdict

from .activity_context_geometry import table_dependency_order
from .activity_continuation_context import continuation_context_proved
from .activity_continuation_policy import (
    canonical_header,
    caption_prefix,
    compatible_columns,
    continuation_prefix,
    continued_context_prefix,
)
from .activity_header_identity import schema_requires_review
from .activity_headers import context_from_text, grid_schema
from .activity_models import TableContext
from .activity_parallel_context import qualified_panel_context, shared_panel_context
from .activity_table_layout import validate_layout
from .activity_text_plan import validate_text_scope
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
        and not schema_requires_review(schema)
        and layout["semantic_kind"] == schema.semantic_kind
        and layout["value_kinds"] == list(map(list, schema.value_kinds))
        and layout["context"] == asdict(schema.context)
    )


def _edge(parent, current, root):
    a, b, first = parent["layout"], current["layout"], root["layout"]
    boundary = b.get("boundary_prefix", b["prefix"])
    if b["prefix"] != boundary and (
        not b["data_start"] or b["prefix"] != b["context"]["raw_context"]
    ):
        return False
    if (
        b["semantic_kind"] != first["semantic_kind"]
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
        and shared_panel_context(a, a.get("boundary_prefix", a["prefix"]), b, boundary)
        and (
            b["semantic_kind"] == "generic"
            and b["context"] == asdict(qualified_panel_context(b, boundary))
            or b["semantic_kind"] != "generic"
            and b["context"] == first["context"]
            and caption_prefix(boundary, root["table_id"], first["prefix"])
        )
    )
    adjacent = (
        parent["page_no"] + 1 == current["page_no"]
        and b["context"] == a["context"]
        and b["ys"][0] < 130
        and compatible_columns(a["xs"], b["xs"])
        and continuation_prefix(a["suffix"])
        and continued_context_prefix(
            b.get("boundary_prefix", b["prefix"]), TableContext(**a["context"])
        )
        and continuation_context_proved(b, b.get("boundary_prefix", b["prefix"]))
    )
    return same_page or adjacent


def table_scope_groups(records):
    """One original header origin plus complete adjacent/parallel paths.

    No edge can point backwards or cross a gap/unproved field or context change.
    Shared columns keep each proved panel's own conditions; adjacent pages keep
    their immediate parent's context. Different roots remain independent. This
    same scope serves header-only completeness and references, not SAR pooling.
    """
    if len(records) > 25000:
        raise ValueError("Original table scope exceeds its bounded region inventory")
    for record in records:
        validate_layout(record)
        validate_text_scope(record)
    families, invalid, anchors = [], [], {}
    for record in sorted(
        records,
        key=lambda r: table_dependency_order(r["page_no"], r["bbox"]),
    ):
        if record.get("text_scope"):
            scope = record["text_scope"]
            key = [record["page_no"], *scope["span"]]
            if scope["origin"] == key and scope["parent"] is None:
                families.append([record])
            else:
                options = [
                    f
                    for f in families
                    if f[0].get("text_scope")
                    and f[0]["text_scope"]["origin"] == scope["origin"]
                    and any(
                        [p["page_no"], *p["text_scope"]["span"]] == scope["parent"]
                        and p["page_no"] + 1 == record["page_no"]
                        for p in f
                    )
                ]
                if len(options) == 1:
                    if len(options[0]) >= 128:
                        raise ValueError(
                            "Connected original text table exceeds its bounded region inventory"
                        )
                    options[0].append(record)
                else:
                    invalid.append(record)
            continue
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
        if region.get("layout") or region.get("text_scope"):
            origin = (
                tuple(region["text_scope"]["origin"])
                if region.get("text_scope")
                else _anchor(region["layout"])
            )
            key = (region["kind"], region["table_id"].casefold(), origin)
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
