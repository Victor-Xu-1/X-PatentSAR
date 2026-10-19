"""Shared current-grid row conservation and exact physical cell proof."""

from collections import defaultdict

from .activity_context_values import CONTEXT_IDENTITY_FIELDS
from .activity_metadata import metadata_field
from .activity_result_references import _get, _source_matches
from .table_cells import activity_kind_matches


def source_layout_matches(source, region):
    layout = region["layout"]
    xs, ys = layout["xs"], layout["ys"]
    row, pair = source.get("row"), source.get("pair")
    if (
        type(row) is not int
        or not layout["data_start"] <= row < len(ys) - 1
        or type(pair) is not int
        or not 0 <= pair < len(layout["columns"])
        or source.get("header_region") != layout["header_origin"]
        or any(
            source.get(key) != layout["context"][key]
            for key in (
                *CONTEXT_IDENTITY_FIELDS,
                "raw_caption",
                "body_text",
                "raw_context",
            )
        )
    ):
        return False
    group = layout["columns"][pair]
    expected = [
        (group[0], "compound_id"),
        *group[1],
        *[(column, metadata_field(kind)) for column, kind in group[2]],
    ]
    cells = source.get("cells", [])
    value_kinds = dict(layout["value_kinds"])
    if not isinstance(cells, list) or len(cells) != len(expected):
        return False
    for cell, (column, field) in zip(cells, expected):
        if not isinstance(cell, dict) or cell.get("field") != field:
            return False
        kind = value_kinds.get(column)
        if kind and not activity_kind_matches(cell.get("value", ""), kind):
            return False
        if (
            type(cell.get("physical_column")) is not int
            or cell.get("physical_column") != column
            or cell.get("bbox")
            != [
                xs[column],
                ys[row],
                xs[column + 1],
                ys[row + 1],
            ]
        ):
            return False
        if (
            layout["raw_headers"]
            and cell.get("raw_header") != layout["raw_headers"][column]
        ):
            return False
    return True


def table_row_errors(regions, rows):
    """No reference sentence is needed for every recorded grid to conserve rows."""
    grids = [r for r in regions if r.get("layout")]
    if rows is None:
        return (
            ["Current original table layouts require their source rows."]
            if grids
            else []
        )
    if not isinstance(rows, list) or len(rows) > 25000:
        raise ValueError("Original grid rows exceed their bounded inventory")
    owned = {(r["page_no"], tuple(r["bbox"])): r for r in grids}
    packets, unknown, count = defaultdict(list), False, 0
    for row in rows:
        sources = _get(row, "activity_sources", [])
        if not isinstance(sources, list) or len(sources) > 500:
            raise ValueError("Malformed or unbounded original grid sources")
        count += len(sources)
        if count > 100000:
            raise ValueError("Original grid sources exceed their bound")
        for source in sources:
            if not isinstance(source, dict):
                raise TypeError("Malformed original grid source")
            if source.get("orientation") == "transposed":
                continue  # The same coverage pass checks its column inventory.
            box = source.get("table_bbox")
            if box is None:
                unknown |= _get(row, "source") == "observed_grid_cells"
                continue  # Other existing readers have their own source contract.
            if (
                not isinstance(box, list)
                or len(box) != 4
                or any(type(x) not in (int, float) for x in box)
                or type(source.get("page_no")) is not int
            ):
                raise ValueError("Malformed original grid identity")
            key = (source.get("page_no"), tuple(box))
            if key in owned:
                packets[key].append((row, source))
            else:
                unknown = True
    errors = ["An original grid row has no owned physical region."] if unknown else []
    for key, region in owned.items():
        observations = packets[key]
        positions = [(s.get("row"), s.get("pair")) for _, s in observations]
        if (
            len(observations) != region["row_count"]
            or any(type(a) is not int or type(b) is not int for a, b in positions)
            or len(set(positions)) != len(positions)
            or any(
                not source_layout_matches(source, region)
                or not _source_matches(row, source, region)
                for row, source in observations
            )
        ):
            errors.append(
                f"Unproved original grid row and cell population p{region['page_no']} ({region['region_id']})."
            )
    return errors
