"""Column adapters over the sole original body-context and diagram authority."""

from .activity_context_geometry import context_band, context_region, grid_box
from .source_body_context import (
    intersecting_source_diagrams,
    original_context_extent,
    validate_page_diagrams,
)
from .source_window_chunks import project_source_window
from .structure_table_headers import structure_column_pairs
from .unruled_scope import scope_axes, scope_body_top, scope_headers


def body_context_window(scope):
    return [0, scope_body_top(scope), *scope["page_size"]]


def column_context_window(scope):
    """Derive ownership from the shared original-grid context SDK, not page y."""
    complete = body_context_window(scope)
    geometry = scope.get("context_geometry")
    if scope.get("kind") == "continued_ruled_columns":
        geometry = context_region(
            scope["grid_axes"], [grid_box(grid) for grid in scope["page_grids"]]
        )["context_geometry"]
    if geometry is None:
        return complete
    left, right = context_band(geometry)
    return [max(0, left), complete[1], min(complete[2], right), complete[3]]


def original_body_extent(scope, chunks, diagrams):
    validate_page_diagrams(diagrams, scope["page_size"])
    complete = body_context_window(scope)
    window = column_context_window(scope)
    projected = project_source_window(chunks, complete, window)
    extent = original_context_extent(
        projected,
        window,
        intersecting_source_diagrams(diagrams, window),
    )
    if scope.get("kind") is None:
        # A later actual closed frame has its own row authority, even when its
        # columns or ancestry are unresolved. Keep full raw context, but do not
        # let a logical matcher publish those same physical rows first.
        bottom = min(
            [
                extent["body_bottom"],
                *[
                    grid["ys"][0]
                    for grid in scope["page_grids"]
                    if grid["ys"][0] >= scope_body_top(scope)
                ],
            ]
        )
        extent = {
            **extent,
            "body_bottom": bottom,
            "trusted_bottom": min(extent["trusted_bottom"], bottom),
            "unproved_boundaries": [
                b for b in extent["unproved_boundaries"] if b["bbox"][1] < bottom
            ],
        }
    return extent


def original_body_bottom(scope, chunks, diagrams):
    return original_body_extent(scope, chunks, diagrams)["body_bottom"]


def column_body_extent(source):
    """Recompute inventory/trusted bounds from the same complete source facts."""
    return original_body_extent(
        source["header_scope"], source["body_context"], source["page_diagrams"]
    )


def column_boundary_issues(extent):
    return [
        {"cpd": "", "reason": "unproved_original_column_boundary", "boundary": boundary}
        for boundary in extent["unproved_boundaries"]
    ]


def trusted_column_diagrams(source, diagrams):
    bottom = column_body_extent(source)["trusted_bottom"]
    return [diagram for diagram in diagrams if diagram["bbox"][3] <= bottom]


def body_diagrams(scope, bottom, diagrams):
    xs, ys = scope_axes(scope)
    pairs = structure_column_pairs(scope_headers(scope))
    return [
        d
        for d in diagrams
        if d["bbox"][3] > ys[1]
        and d["bbox"][1] < bottom
        and any(
            min(d["bbox"][2], xs[s + 1]) > max(d["bbox"][0], xs[s]) for _, s in pairs
        )
    ]
