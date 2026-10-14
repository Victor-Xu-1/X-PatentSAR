"""One bounded original layout descriptor per physical generic grid."""

import math
from dataclasses import asdict, replace
from itertools import pairwise

from .activity_grid_context import _suffix


def prepare_layout(schema, page_no, region, tokens, prefix, regions):
    confirmed_context = bool(
        schema.first_data_row > 0
        and schema.header_resolution
        and schema.header_resolution.get("status") == "observed_header_consensus"
    )
    layout = {
        "xs": list(region["xs"]),
        "ys": list(region["ys"]),
        "data_start": schema.first_data_row,
        "header_origin": {
            "page_no": schema.header_region[0],
            "bbox": list(schema.header_region[1]),
        }
        if schema.header_region
        else None,
        "prefix": schema.context.raw_context if confirmed_context else prefix,
        "boundary_prefix": prefix,
        "suffix": _suffix(tokens, region, regions),
        "raw_headers": list(schema.raw_headers) if schema.first_data_row else [],
        "context": asdict(schema.context),
        "semantic_kind": schema.semantic_kind,
        "value_kinds": list(map(list, schema.value_kinds)),
        "columns": [
            [
                group.id_column,
                list(map(list, group.value_columns)),
                list(map(list, group.metadata_columns)),
            ]
            for group in schema.groups
        ],
    }
    return replace(schema, source_layout=layout)


def validate_layout(record):
    layout = record.get("layout")
    if layout is None:
        return
    if (
        record["kind"] != "grid"
        or not isinstance(layout, dict)
        or set(layout) - {"boundary_prefix"}
        != {
            "xs",
            "ys",
            "data_start",
            "header_origin",
            "prefix",
            "suffix",
            "raw_headers",
            "columns",
            "context",
            "semantic_kind",
            "value_kinds",
        }
    ):
        raise ValueError("Malformed original table layout")
    for key, maximum in (("xs", 501), ("ys", 25001)):
        axis = layout[key]
        if (
            not isinstance(axis, list)
            or not 2 <= len(axis) <= maximum
            or any(
                type(x) not in (int, float)
                or not math.isfinite(x)
                or not 0 <= x <= 100000
                for x in axis
            )
            or any(b <= a for a, b in pairwise(axis))
        ):
            raise ValueError("Malformed original table axes")
    xs, ys = layout["xs"], layout["ys"]
    if (
        record["bbox"] != [xs[0], ys[0], xs[-1], ys[-1]]
        or type(layout["data_start"]) is not int
        or not 0 <= layout["data_start"] < len(ys)
    ):
        raise ValueError("Original table layout is not owned by its region")
    context = layout["context"]
    if (
        not isinstance(context, dict)
        or set(context)
        != {
            "table_id",
            "caption",
            "target",
            "assay",
            "cell_line",
            "raw_caption",
            "body_text",
            "raw_context",
        }
        or any(
            value is None
            and key not in {"target", "assay", "cell_line"}
            or value is not None
            and (not isinstance(value, str) or len(value) > 10000)
            for key, value in context.items()
        )
        or context["table_id"] != record["table_id"]
    ):
        raise ValueError("Malformed original table context")
    for key in (
        "prefix",
        "suffix",
        *(("boundary_prefix",) if "boundary_prefix" in layout else ()),
    ):
        if not isinstance(layout[key], str) or len(layout[key]) > 10000:
            raise ValueError("Original table boundary text exceeds its bound")
    headers = layout["raw_headers"]
    if (
        not isinstance(headers, list)
        or headers
        and len(headers) != len(xs) - 1
        or any(not isinstance(h, str) or len(h) > 4096 for h in headers)
    ):
        raise ValueError("Malformed original physical headers")
    groups, used = layout["columns"], set()
    if not isinstance(groups, list) or not 1 <= len(groups) <= 250:
        raise ValueError("Malformed original table column groups")
    for group in groups:
        if (
            not isinstance(group, list)
            or len(group) != 3
            or not isinstance(group[1], list)
            or not isinstance(group[2], list)
        ):
            raise ValueError("Malformed original table columns")
        pairs = group[1] + group[2]
        if any(
            not isinstance(pair, list)
            or len(pair) != 2
            or not isinstance(pair[1], str)
            or len(pair[1]) > 256
            for pair in pairs
        ):
            raise ValueError("Malformed original table field")
        for column in [group[0], *[pair[0] for pair in pairs]]:
            if (
                type(column) is not int
                or not 0 <= column < len(xs) - 1
                or column in used
            ):
                raise ValueError("Original table columns overlap or exceed geometry")
            used.add(column)
    if used != set(range(len(xs) - 1)):
        raise ValueError("Original table layout contains unowned columns")
    kinds = layout["value_kinds"]
    value_columns = {pair[0] for group in groups for pair in group[1]}
    if (
        layout["semantic_kind"] not in {"generic", "biology"}
        or not isinstance(kinds, list)
        or any(
            not isinstance(pair, list)
            or len(pair) != 2
            or type(pair[0]) is not int
            or pair[0] not in value_columns
            or pair[1] not in {"number", "letter", "plus"}
            for pair in kinds
        )
        or len({pair[0] for pair in kinds}) != len(kinds)
        or (layout["semantic_kind"] == "generic" and bool(kinds))
        or (
            layout["semantic_kind"] == "biology"
            and {pair[0] for pair in kinds} != value_columns
        )
    ):
        raise ValueError("Malformed original table value roles")
    origin = layout["header_origin"]
    if origin is not None and (
        not isinstance(origin, dict)
        or set(origin) != {"page_no", "bbox"}
        or type(origin["page_no"]) is not int
        or not 1 <= origin["page_no"] <= record["page_no"]
        or not isinstance(origin["bbox"], list)
        or len(origin["bbox"]) != 4
        or any(
            type(x) not in (int, float) or not math.isfinite(x) or not 0 <= x <= 100000
            for x in origin["bbox"]
        )
        or origin["bbox"][0] >= origin["bbox"][2]
        or origin["bbox"][1] >= origin["bbox"][3]
    ):
        raise ValueError("Malformed original header origin")
