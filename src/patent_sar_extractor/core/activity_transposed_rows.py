"""Conserve transposed original columns through extraction and saved replay."""

from collections import defaultdict

from .activity_context_values import CONTEXT_IDENTITY_FIELDS, CONTEXT_TEXT_FIELDS
from .activity_result_references import _get, _source_matches
from .activity_transposed_context import transposed_context_matches
from .activity_transposed_source import declared_compound
from .source_cell_claims import cell_source_conflict


def _key(source):
    box = source.get("table_bbox")
    return (
        (source.get("page_no"), tuple(box))
        if type(source.get("page_no")) is int
        and isinstance(box, list)
        and len(box) == 4
        and all(type(value) in {int, float} for value in box)
        else None
    )


def _source_geometry_matches(row, source, region, column):
    xs, ys = region["grid_axes"]["xs"], region["grid_axes"]["ys"]
    layout = region["transposed_layout"]
    header = layout["header_row"]
    cells = source.get("cells")
    if (
        source.get("orientation") != "transposed"
        or not transposed_context_matches(layout, region["grid_axes"])
        or any(
            source.get(key) != layout["context"][key]
            for key in (*CONTEXT_IDENTITY_FIELDS, *CONTEXT_TEXT_FIELDS)
            if key != "caption"
        )
        or source.get("row") != header
        or not isinstance(cells, list)
        or len(cells) != len(ys) - header - 1
        or source.get("header_region")
        != {
            "page_no": region["page_no"],
            "bbox": [xs[0], ys[0], xs[-1], ys[header + 1]],
        }
        or _get(row, "cpd")
        != declared_compound(layout["columns"][column][header]["text"])
    ):
        return False
    for row_index, cell in enumerate(cells, header):
        bounds = [xs[column], ys[row_index], xs[column + 1], ys[row_index + 1]]
        original = layout["columns"][column][row_index]
        if (
            not isinstance(cell, dict)
            or cell.get("bbox") != bounds
            or not isinstance(cell.get("value"), str)
            or row_index == header
            and cell.get("field") != "compound_id"
            or row_index > header
            and (
                cell.get("raw_header") != layout["columns"][0][row_index]["text"]
                or cell.get("metric_header_bbox")
                != [xs[0], ys[row_index], xs[1], ys[row_index + 1]]
            )
            or cell_source_conflict(
                {
                    "method": "native_cell"
                    if original["origin"] == "native"
                    else "page_ocr_cell",
                    "text": original["text"],
                    "bbox": bounds,
                    "source_observation": original,
                },
                cell["value"],
                "id" if row_index == header else "number",
            )
        ):
            return False
    return _source_matches(row, source, region)


def transposed_row_errors(regions, rows):
    roots = {
        (record["page_no"], tuple(record["bbox"])): record
        for record in regions
        if "transposed_layout" in record
    }
    children, sources = defaultdict(dict), defaultdict(list)
    for record in regions:
        scope = record.get("column_scope")
        if scope is None:
            continue
        key = record["page_no"], tuple(scope["parent_grid"])
        root = roots.get(key)
        column = scope["column"]
        if (
            root is None
            or column in children[key]
            or column >= len(root["transposed_layout"]["columns"])
            or scope["header_row"] != root["transposed_layout"]["header_row"]
            or record["table_id"] != root["table_id"]
            or record["header"]
            != root["transposed_layout"]["columns"][column][scope["header_row"]][
                "text"
            ][:1024]
        ):
            raise ValueError("Unresolved original column has no unique physical source")
        children[key][column] = record
    if rows is None:
        return (
            ["Current transposed layouts require their source rows."] if roots else []
        )
    if not isinstance(rows, list) or len(rows) > 25000:
        raise ValueError("Original transposed rows exceed their bounded inventory")
    unknown, count = False, 0
    for row in rows:
        source_kind = _get(row, "source", "")
        if not isinstance(source_kind, str):
            raise TypeError("Malformed original transposed row source")
        packets = _get(row, "activity_sources", [])
        if not isinstance(packets, list) or len(packets) > 500:
            raise ValueError("Malformed original transposed sources")
        count += len(packets)
        if count > 100000:
            raise ValueError("Original transposed sources exceed their bound")
        for source in packets:
            if not isinstance(source, dict):
                raise TypeError("Malformed original transposed source")
            key = _key(source)
            if source.get("orientation") == "transposed":
                if key not in roots:
                    unknown = True
                else:
                    sources[key].append((row, source))
            elif "observed_transposed_cells" in source_kind.split("+") and not key:
                unknown = True
    errors = (
        ["A transposed row has no owned original physical source."] if unknown else []
    )
    for key, root in roots.items():
        layout = root["transposed_layout"]
        header = layout["header_row"]
        population = defaultdict(list)
        valid = len(sources[key]) == root["row_count"]
        for row, source in sources[key]:
            column = source.get("pair")
            if type(column) is not int or not 1 <= column < len(layout["columns"]):
                valid = False
                continue
            population[column].append((row, source))
        for column in range(1, len(layout["columns"])):
            label = declared_compound(layout["columns"][column][header]["text"])
            found, unresolved = population[column], children[key].get(column)
            if not label or not found:
                valid &= bool(
                    not found
                    and unresolved is not None
                    and unresolved["reason"]
                    == ("no_original_rows" if label else "unsupported_header")
                )
            else:
                valid &= bool(
                    unresolved is None
                    and len(found) == 1
                    and _source_geometry_matches(*found[0], root, column)
                )
        if not valid:
            errors.append(
                f"Unproved original transposed column population p{root['page_no']} ({root['region_id']})."
            )
    return errors
