"""Registered original column facts, separate from matching and publication."""

from .activity_context_geometry import validate_grid_axes
from .source_body_context import contained_source_diagrams
from .structure_table_headers import aligned_column_edges
from .unruled_body_scope import original_body_bottom
from .unruled_region_observation import observe_column_body
from .unruled_scope import scope_axes, scope_roles

ANCHOR_ROLE = "structure_column_anchor"
ANCHOR_STATUS = "observed_original_structure_columns"


def observe_column_anchor(tokens, header, diagrams, *, grid=None):
    return {
        "status": ANCHOR_STATUS,
        "version": 1,
        "grid_axes": grid if grid is not None else header["grid_axes"],
        **observe_column_body(tokens, header, diagrams),
    }


def column_anchor_diagrams(source):
    """The registered physical grid owns its data frame, not other page regions."""
    header, grid = source["header_scope"], source["grid_axes"]
    start = int(header.get("kind") == "original_ruled_columns")
    frame = [
        grid["xs"][0],
        grid["ys"][start],
        grid["xs"][-1],
        min(grid["ys"][-1], source["body_bottom"]),
    ]
    if frame[1] >= frame[3]:
        return []  # A proved header-only frame has no closed data rows.
    return contained_source_diagrams(source["page_diagrams"], frame)


def column_anchor_roles(source):
    if (
        not isinstance(source, dict)
        or set(source)
        != {
            "status",
            "version",
            "header_scope",
            "grid_axes",
            "body_context",
            "page_diagrams",
            "body_bottom",
        }
        or source["status"] != ANCHOR_STATUS
        or type(source["version"]) is not int
        or source["version"] != 1
    ):
        raise ValueError("Malformed original structure-column anchor")
    roles = scope_roles(source["header_scope"])
    header = source["header_scope"]
    grid = source["grid_axes"]
    if (
        not isinstance(grid, dict)
        or set(grid) != {"xs", "ys"}
        or any(not isinstance(grid[k], list) or len(grid[k]) < 2 for k in ("xs", "ys"))
    ):
        raise ValueError("Malformed original column-anchor grid")
    validate_grid_axes(
        grid, [grid["xs"][0], grid["ys"][0], grid["xs"][-1], grid["ys"][-1]]
    )
    if (
        not 0 <= grid["xs"][0] < grid["xs"][-1] <= header["page_size"][0]
        or not 0 <= grid["ys"][0] < grid["ys"][-1] <= header["page_size"][1]
    ):
        raise ValueError("Original column-anchor grid leaves its page")
    if header.get("kind") == "original_ruled_columns":
        if grid != header["grid_axes"]:
            raise ValueError("Original header and physical column-anchor grid differ")
    elif (
        header.get("kind") != "continued_unruled_columns"
        or not aligned_column_edges(scope_axes(header)[0], grid["xs"])
        or grid["ys"][0] < scope_axes(header)[1][1]
    ):
        raise ValueError("Unproved original physical continuation columns")
    if (
        type(source["body_bottom"]) not in {int, float}
        or not scope_axes(header)[1][1]
        < source["body_bottom"]
        <= header["page_size"][1]
    ):
        raise ValueError("Invalid original column-anchor body extent")
    if source["body_bottom"] != original_body_bottom(
        source["header_scope"], source["body_context"], source["page_diagrams"]
    ):
        raise ValueError("Original column-anchor boundary differs from its full source")
    return roles
