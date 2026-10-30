"""Clipping owners from the original unruled-header partition, never grid rules."""

from .cell_frame_proof import inside_box


def logical_title_exclusions(context, bounds):
    """Keep the full source; qualify only its independently owned title column.

    The unruled-header consumer rederives this clipping window from the complete
    original header and independently positioned captions. It is not a printed
    table boundary or a new ownership claim. A crossing whole mark still refuses.
    """
    logical = context.get("logical_window")
    if logical is None:
        return []
    if (
        context.get("geometry") is not None
        or context.get("grid_axes") is not None
        or "parallel_grids" in context
        or "page_grids" in context
        or not inside_box(logical, [0, 0, bounds[2], 100000])
        or bounds[0] != 0
        or bounds[3] != logical[1]
        or bounds[1] != max(0, logical[1] - 310)
        or logical[0] == 0
        and logical[2] == bounds[2]
    ):
        raise ValueError("Invalid original logical-title clipping owner")
    outside = []
    if logical[0] > 0:
        outside.append([bounds[0], bounds[1], logical[0], bounds[3]])
    if logical[2] < bounds[2]:
        outside.append([logical[2], bounds[1], bounds[2], bounds[3]])
    return outside
