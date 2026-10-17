"""One original horizontal context adapter, separate from printed grid facts."""

from .activity_context_geometry import context_band, context_region, grid_box


def column_context_band(scope):
    """Keep logical words and physical neighbours in their own source domain."""
    width = scope["page_size"][0]
    geometry = scope.get("context_geometry")
    kind = scope.get("kind")
    if kind == "continued_ruled_columns":
        geometry = context_region(
            scope["grid_axes"], [grid_box(grid) for grid in scope["page_grids"]]
        )["context_geometry"]
    if geometry is not None:
        left, right = context_band(geometry)
    elif kind is None:
        left, right = scope["column_band"]
    elif kind == "continued_unruled_columns":
        left, right = column_context_band(scope["anchor_scope"])
    else:
        raise ValueError("Original column scope has no horizontal source authority")
    return [max(0, left), min(width, right)]
