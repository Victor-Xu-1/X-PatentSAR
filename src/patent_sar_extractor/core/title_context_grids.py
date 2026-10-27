"""Original catalogue grid context and its independently closed ruling cells."""

from itertools import pairwise

from .activity_context_geometry import (
    MAX_TABLES,
    context_floor,
    context_region,
    grid_axes,
    grid_box,
    validate_context_geometry,
    validate_grid_axes,
)
from .cell_frame_proof import inside_box
from .cell_raster import cell_pixel_rect
from .source_cell_pixels import MAX_CELL_PIXELS, source_window

MAX_TITLE_CELLS = 25000


def parallel_title_grids(geometry, grids):
    """Retain actual overlapping-body peers, not nearest titles or page halves."""
    if geometry is None or grids is None:
        return None
    if not isinstance(grids, list) or not 1 <= len(grids) <= MAX_TABLES:
        raise ValueError("Original title grid inventory exceeds its bound")
    target = geometry["table_bbox"]
    peers = []
    for grid in grids:
        axes, box = grid_axes(grid), grid_box(grid)
        validate_grid_axes(axes, box)
        if box == target or (
            min(box[3], target[3]) > max(box[1], target[1])
            and (box[2] <= target[0] or box[0] >= target[2])
        ):
            peers.append(axes)
    return (
        sorted(peers, key=lambda g: (g["xs"][0], g["ys"][0]))
        if len(peers) > 1
        else None
    )


def title_context_spec(
    *,
    geometry=None,
    logical_window=None,
    grid_axes=None,
    parallel_grids=None,
    page_grids=None,
):
    return {
        "geometry": geometry,
        "logical_window": logical_window,
        "grid_axes": grid_axes,
        **({"parallel_grids": parallel_grids} if parallel_grids is not None else {}),
        **({"page_grids": page_grids} if page_grids is not None else {}),
    }


def validate_parallel_title_grids(context):
    peers = context.get("parallel_grids")
    if peers is None:
        if "parallel_grids" in context or "page_grids" in context:
            raise ValueError("A parallel title inventory cannot be null")
        return None
    geometry, target = context["geometry"], context["grid_axes"]
    if (
        geometry is None
        or target is None
        or context["logical_window"] is not None
        or not isinstance(peers, list)
        or not 2 <= len(peers) <= MAX_TABLES
    ):
        raise ValueError("Malformed original parallel title grids")
    boxes = []
    for axes in peers:
        try:
            box = grid_box(axes)
        except (KeyError, TypeError, IndexError) as error:
            raise ValueError("Malformed original parallel title axes") from error
        validate_grid_axes(axes, box)
        boxes.append(box)
    if (
        peers != sorted(peers, key=lambda g: (g["xs"][0], g["ys"][0]))
        or sum(axes == target for axes in peers) != 1
        or any(a[2] > b[0] for a, b in pairwise(boxes))
        or any(
            min(b[3], geometry["table_bbox"][3]) <= max(b[1], geometry["table_bbox"][1])
            for b in boxes
        )
    ):
        raise ValueError("Ambiguous original parallel title grid ownership")
    grids = context.get("page_grids")
    if not isinstance(grids, list) or not 2 <= len(grids) <= MAX_TABLES:
        raise ValueError("Missing complete original page grid inventory")
    page_boxes = []
    for grid in grids:
        try:
            box = grid_box(grid)
        except (KeyError, TypeError, IndexError) as error:
            raise ValueError("Malformed original page title grid") from error
        validate_grid_axes(grid, box)
        page_boxes.append(box)
    if (
        len({tuple(box) for box in page_boxes}) != len(page_boxes)
        or sum(grid == target for grid in grids) != 1
        or geometry != context_region(target, page_boxes)["context_geometry"]
        or peers != parallel_title_grids(geometry, grids)
    ):
        raise ValueError("Title family differs from its original page grid inventory")
    return peers


def context_ruling_cells(context, bounds):
    """Only actual original first rows can supply boundary-rule exemptions."""
    if not isinstance(context, dict) or set(context) - {
        "parallel_grids",
        "page_grids",
    } != {
        "geometry",
        "logical_window",
        "grid_axes",
    }:
        raise ValueError("Malformed original title discovery context")
    geometry, logical, axes = (
        context[name] for name in ("geometry", "logical_window", "grid_axes")
    )
    if geometry is not None:
        if logical is not None:
            raise ValueError("Mixed physical and logical title contexts")
        validate_context_geometry(geometry, geometry.get("table_bbox"))
        box = geometry["table_bbox"]
        from .title_family_geometry import family_title_bounds

        if bounds != family_title_bounds(
            context, [0, context_floor(geometry), bounds[2], box[1]]
        ):
            raise ValueError("Title discovery leaves its original context")
    elif logical is not None:
        if not inside_box(logical, [0, 0, bounds[2], 100000]):
            raise ValueError("Invalid original logical title context")
        if bounds != [0, max(0, logical[1] - 310), bounds[2], logical[1]]:
            raise ValueError("Title discovery leaves its logical context")
    peers = validate_parallel_title_grids(context)
    if axes is None:
        return []
    if geometry is None:
        raise ValueError("Title ruling needs original physical grid ownership")
    validate_grid_axes(axes, geometry["table_bbox"])
    grids = peers or [axes]
    if sum(len(grid["xs"]) - 1 for grid in grids) > MAX_TITLE_CELLS:
        raise ValueError("Original title ruling inventory exceeds the grid bound")
    first_rows = [
        [left, grid["ys"][0], right, grid["ys"][1]]
        for grid in grids
        for left, right in pairwise(grid["xs"])
    ]
    from .title_family_geometry import family_body_cells

    cells = [
        list(cell)
        for cell in dict.fromkeys(
            tuple(cell) for cell in [*first_rows, *family_body_cells(context, bounds)]
        )
    ]
    if len(cells) > MAX_TITLE_CELLS:
        raise ValueError("Original title cell inventory exceeds the grid bound")
    return cells


def title_ruling_budget(cells, size):
    return (
        sum(
            rectangle.width * rectangle.height
            for cell in cells
            for rectangle in (cell_pixel_rect(source_window(cell, size), 600),)
        )
        <= MAX_CELL_PIXELS
    )


def caption_title_context(scope):
    context = title_context_spec(
        geometry=scope["context_geometry"],
        grid_axes=scope["grid_axes"],
    )
    if "parallel_grids" in scope:
        context["parallel_grids"] = scope["parallel_grids"]
    if "page_grids" in scope:
        context["page_grids"] = scope["page_grids"]
    return context
