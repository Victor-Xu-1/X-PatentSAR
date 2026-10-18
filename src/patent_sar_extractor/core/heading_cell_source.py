"""One original grid-owned heading window, never a successful-token crop."""

from bisect import bisect_right

from .activity_context_geometry import (
    MAX_TABLES,
    grid_axes,
    grid_box,
    validate_grid_axes,
)
from .cell_frame_proof import inside_box
from .source_cell_pixels import observe_closed_cell


def selected_cell(inventory, nomination, size, maximum_height):
    if not isinstance(inventory, list) or len(inventory) > MAX_TABLES:
        raise ValueError("Original heading grid inventory exceeds its bound")
    candidates = set()
    for axes in inventory:
        box = grid_box(axes)
        validate_grid_axes(axes, box)
        if not inside_box(box, [0, 0, *size]):
            raise ValueError("Original heading grid leaves its page")
        if not inside_box(nomination, box):
            if min(nomination[2], box[2]) > max(nomination[0], box[0]) and min(
                nomination[3], box[3]
            ) > max(nomination[1], box[1]):
                return None  # A crossing source is not assigned by its centre.
            continue
        xs, ys = axes["xs"], axes["ys"]
        column, row = (
            bisect_right(xs, nomination[0]) - 1,
            bisect_right(ys, nomination[1]) - 1,
        )
        if column + 1 >= len(xs) or row + 1 >= len(ys):
            return None
        cell = [xs[column], ys[row], xs[column + 1], ys[row + 1]]
        if not inside_box(nomination, cell) or cell[3] - cell[1] > maximum_height:
            return None
        candidates.add(tuple(cell))
    return list(next(iter(candidates))) if len(candidates) == 1 else None


def observe_cell_source(page, nomination, grids, maximum_height):
    inventory = [grid_axes(grid) for grid in grids]
    size = [page.rect.width, page.rect.height]
    cell = selected_cell(inventory, nomination, size, maximum_height)
    if cell is None or (pixels := observe_closed_cell(page, cell)) is None:
        return None
    return {"version": 1, "grid_inventory": inventory, "cell": cell, "pixels": pixels}


def valid_cell_geometry(packet, nomination, size, maximum_height):
    if (
        not isinstance(packet, dict)
        or set(packet) != {"version", "grid_inventory", "cell", "pixels"}
        or type(packet["version"]) is not int
        or packet["version"] != 1
    ):
        return False
    try:
        selected = selected_cell(
            packet["grid_inventory"], nomination, size, maximum_height
        )
        return selected is not None and packet["cell"] == selected
    except (ValueError, TypeError, KeyError, IndexError):
        return False
