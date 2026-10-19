"""Pure physical header-location contract; no OCR, values or source mutation."""

from .activity_context_geometry import grid_box, validate_grid_axes
from .activity_header_identity import compact_header, context_conflict, header_conflict
from .activity_headers import context_from_text, grid_schema
from .cell_frame_proof import valid_cell_frame

PHYSICAL_METHODS = ("physical_header_layout_400dpi", "physical_header_layout_600dpi")


def agreed_layout(candidates, width, limit):
    if len(candidates) != 2 or any(c is None for c in candidates):
        return None
    first, second = candidates
    if (
        first.first_data_row != second.first_data_row
        or not 1 <= first.first_data_row <= limit
        or any(len(c.raw_headers) != width for c in candidates)
        or tuple(g.id_column for g in first.groups)
        != tuple(g.id_column for g in second.groups)
        or tuple(map(compact_header, first.raw_headers))
        != tuple(map(compact_header, second.raw_headers))
        or compact_header(first.context.raw_caption)
        != compact_header(second.context.raw_caption)
    ):
        return None
    return first


def known_discovery_conflict(originals, fresh):
    """Known endpoint/unit/condition/column claims cannot be outvoted by a scout."""
    for observed in originals:
        old = grid_schema(
            context_from_text(observed["prefix"], observed["prefix"]),
            observed["matrix"],
        )
        if old is not None and (
            len(old.raw_headers) != len(fresh.raw_headers)
            or tuple(g.id_column for g in old.groups)
            != tuple(g.id_column for g in fresh.groups)
            or context_conflict(old.context, fresh.context)
            or any(
                header_conflict(a, b)
                for a, b in zip(old.raw_headers, fresh.raw_headers)
            )
        ):
            return True
    return False


def physical_discovery_views(proof):
    """Enumerate bounded row carriers for shared proof and original-pixel replay."""
    observations = proof.get("discovery_observations", [])
    if not isinstance(observations, list) or len(observations) > 4:
        raise ValueError("Malformed original header discovery inventory")
    selected = [
        o
        for o in observations
        if isinstance(o, dict) and o.get("method") in PHYSICAL_METHODS
    ]
    for observed in selected:
        rows = observed.get("rows")
        if (
            not isinstance(rows, list)
            or not 1 <= len(rows) <= 3
            or any(
                not isinstance(row, dict)
                or not isinstance(row.get("columns"), list)
                or not 2 <= len(row["columns"]) <= 64
                or any(not isinstance(column, dict) for column in row["columns"])
                for row in rows
            )
        ):
            raise ValueError("Malformed original physical discovery row carrier")
    return selected


def valid_physical_discovery(proof, validate_column):
    """Only locator fields may contribute to a final independently read header."""
    try:
        views = physical_discovery_views(proof)
        if not views:
            return True
        if len(views) != 2 or [o.get("method") for o in views] != list(
            PHYSICAL_METHODS
        ):
            return False
        axes = views[0]["grid_axes"]
        bounds = grid_box(axes)
        validate_grid_axes(axes, bounds)
        width, count = len(axes["xs"]) - 1, len(axes["ys"]) - 1
        if not 1 <= count <= 3 or not 2 <= width <= 64:
            return False
        candidates = []
        for observed, dpi in zip(views, (400, 600)):
            if (
                set(observed)
                != {"method", "bbox", "grid_axes", "prefix", "matrix", "rows"}
                or observed["grid_axes"] != axes
                or observed["bbox"] != bounds
                or not isinstance(observed["prefix"], str)
                or len(observed["prefix"]) > 10000
                or not isinstance(observed["matrix"], list)
                or len(observed["matrix"]) != count
                or not isinstance(observed["rows"], list)
                or len(observed["rows"]) != count
            ):
                return False
            matrix = observed["matrix"]
            if any(
                not isinstance(row, list)
                or len(row) != width
                or any(not isinstance(text, str) or len(text) > 4096 for text in row)
                for row in matrix
            ):
                return False
            candidate = grid_schema(
                context_from_text(observed["prefix"], observed["prefix"]), matrix
            )
            if candidate is None:
                return False
            for index, (row, words) in enumerate(zip(observed["rows"], matrix)):
                band = [
                    axes["xs"][0],
                    axes["ys"][index],
                    axes["xs"][-1],
                    axes["ys"][index + 1],
                ]
                if (
                    not isinstance(row, dict)
                    or set(row) != {"bbox", "columns"}
                    or row["bbox"] != band
                    or not isinstance(row["columns"], list)
                    or len(row["columns"]) != width
                ):
                    return False
                for column_index, (column, text) in enumerate(
                    zip(row["columns"], words)
                ):
                    if (
                        not isinstance(column, dict)
                        or column.get("raw_text") != text
                        or column.get("bbox")
                        != [
                            axes["xs"][column_index],
                            band[1],
                            axes["xs"][column_index + 1],
                            band[3],
                        ]
                        or type(column.get("physical_column")) is not int
                        or column["physical_column"] != column_index
                        or type(column.get("render_dpi")) is not int
                        or column["render_dpi"] != dpi
                        or not valid_cell_frame(
                            column.get("source_frame"), column, column["bbox"], dpi
                        )
                    ):
                        return False
                    blank = (
                        column.get("raw_text") == column.get("text") == ""
                        and column.get("parts") == column.get("detection_parts") == []
                        and column.get("ink_crop_pixels") is None
                        and column.get("border_pixels") == 0
                        and isinstance(column.get("native_text"), str)
                        and not column["native_text"].strip()
                        and column.get("crosses_boundary") is False
                    )
                    if (
                        index < candidate.first_data_row
                        and not blank
                        and not validate_column(column, column_index, text, band, dpi)
                    ):
                        return False
            candidates.append(candidate)
        selected = agreed_layout(candidates, width, count)
        if selected is None or proof.get("header_band_bbox") != [
            bounds[0],
            bounds[1],
            bounds[2],
            axes["ys"][selected.first_data_row],
        ]:
            return False
        originals = [
            o
            for o in proof["discovery_observations"]
            if isinstance(o, dict)
            and o.get("method") in {"header_layout_400dpi", "header_layout_600dpi"}
        ]
        return not known_discovery_conflict(originals, selected)
    except (TypeError, ValueError, KeyError, IndexError, AttributeError):
        return False
