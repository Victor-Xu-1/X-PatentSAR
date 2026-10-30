"""Native open-row claims only within their proved original grid boundaries."""

from .native_window_coverage import native_window_text_complete, valid_native_window
from .native_window_rules import boundary_rule_path
from .source_cell_claims import cell_source_status
from .source_grid_edges import edge_intervals
from .source_observations import source_observation_status


def open_native_cell_qualified(edges, fragment, column, reading):
    """Exclude only complete literal text/empty cells with original edge evidence."""
    try:
        xs = edges["xs"]
        intervals = edge_intervals(edges)
        if (
            type(column) is not int
            or not 0 <= column < len(xs) - 1
            or not isinstance(fragment, dict)
            or set(fragment) != {"edge", "bbox", "status"}
            or fragment not in intervals
            or fragment["status"] != "observed_columns"
            or edges["rule_frame"] is None
            or not isinstance(reading, dict)
            or set(reading)
            != {"method", "text", "bbox", "source_observation", "native_window"}
            or reading["method"] != "native_cell"
        ):
            return False
        bounds = [xs[column], fragment["bbox"][1], xs[column + 1], fragment["bbox"][3]]
        native, window = reading.get("source_observation"), reading.get("native_window")
        if (
            reading.get("bbox") != bounds
            or cell_source_status(reading) not in {"qualified", "unqualified", "empty"}
            or not isinstance(native, dict)
            or not valid_native_window(window, bounds)
            or window["page_size"] != edges["page_size"]
            or window["refusal"] is not None
        ):
            return False
        status = source_observation_status(native, bounds, reading.get("text"))
        if status == "qualified":
            if not native_window_text_complete(window, native):
                return False
        elif status == "empty":
            if any(paint["kind"] == "fill-text" for paint in window["paints"]):
                return False
        else:
            return False
        return all(
            paint["kind"] == "fill-text"
            or paint["kind"] == "stroke-path"
            and boundary_rule_path(paint["rule_path"], bounds)
            for paint in window["paints"]
        )
    except (KeyError, TypeError, ValueError, IndexError):
        return False


def original_open_grid_matches(page, edges):
    """Re-detect the exact ruled inventory from the actual immutable page."""
    from .source_grid_edges import original_grid_edges
    from .table_geometry import detect_ruled_table_regions

    try:
        frame = edges["rule_frame"]
        if not isinstance(frame, dict):
            return False
        grids = detect_ruled_table_regions(page, dpi=frame["dpi"])
        return sum(original_grid_edges(page, grid) == edges for grid in grids) == 1
    except (KeyError, TypeError, ValueError, IndexError, RuntimeError):
        return False
