"""A closed original content cell bounds a heading, never an inferred column."""

from bisect import bisect_right

from .activity_context_geometry import (
    MAX_TABLES,
    grid_axes,
    grid_box,
    validate_grid_axes,
)
from .cell_frame_proof import inside_box
from .heading_source_geometry import MAX_HEADING_HEIGHT
from .plot_reference_pixels import observe_pixels, replay_pixels
from .source_cell_pixels import MAX_CELL_PIXELS, closed_cell_masks, source_window


def _intersects(left, right):
    return min(left[2], right[2]) > max(left[0], right[0]) and min(
        left[3], right[3]
    ) > max(left[1], right[1])


def _selected(inventory, nomination, size):
    if not isinstance(inventory, list) or len(inventory) > MAX_TABLES:
        raise ValueError("Original heading panel inventory exceeds its bound")
    cells, crossing = set(), False
    for axes in inventory:
        bounds = grid_box(axes)
        validate_grid_axes(axes, bounds)
        if not inside_box(bounds, [0, 0, *size]):
            raise ValueError("Original heading panel leaves its page")
        if not _intersects(bounds, nomination):
            continue
        xs, ys = axes["xs"], axes["ys"]
        if not inside_box(nomination, bounds):
            crossing |= bounds[3] - bounds[1] > MAX_HEADING_HEIGHT
            continue
        column, row = (
            bisect_right(xs, nomination[0]) - 1,
            bisect_right(ys, nomination[1]) - 1,
        )
        if column + 1 >= len(xs) or row + 1 >= len(ys):
            crossing = True
            continue
        cell = [xs[column], ys[row], xs[column + 1], ys[row + 1]]
        # Short heading decorations remain the existing text-cell authority.
        # A content panel has physical space beyond that bounded text window.
        if cell[3] - cell[1] <= MAX_HEADING_HEIGHT:
            continue
        if inside_box(nomination, cell):
            cells.add(tuple(cell))
        else:
            crossing = True
    return bool(cells) or crossing, (
        list(next(iter(cells))) if len(cells) == 1 and not crossing else None
    )


def observe_panel(page, heading, grids, *, pixel_cache=None):
    inventory = [grid_axes(grid) for grid in grids]
    size = [page.rect.width, page.rect.height]
    present, cell = _selected(inventory, heading["nomination"]["bbox"], size)
    if not present:
        return None
    pixels, refusal = None, "ambiguous_cell"
    if cell is not None:
        key = (page.number, *cell)
        if pixel_cache is None:
            pixels = observe_pixels(page, source_window(cell, size), MAX_CELL_PIXELS)
            refusal = None if pixels is not None else "pixel_budget"
        else:
            if key not in pixel_cache:
                value = observe_pixels(page, source_window(cell, size), MAX_CELL_PIXELS)
                pixel_cache[key] = (
                    value,
                    None if value is not None else "pixel_budget",
                )
            pixels, refusal = pixel_cache[key]
    return {
        "version": 1,
        "grid_inventory": inventory,
        "cell": cell,
        "pixels": pixels,
        "refusal": refusal,
    }


def panel_bounds(packet, heading):
    """A missing/ambiguous/over-budget frame refuses; it never widens the scope."""
    if not isinstance(packet, dict) or (
        set(packet) != {"version", "grid_inventory", "cell", "pixels", "refusal"}
        or type(packet["version"]) is not int
        or packet["version"] != 1
    ):
        raise ValueError("Malformed original heading panel")
    size = heading["page_size"]
    present, cell = _selected(
        packet["grid_inventory"], heading["nomination"]["bbox"], size
    )
    if not present or packet["cell"] != cell:
        raise ValueError("Original heading panel selection differs")
    if cell is None:
        if packet["pixels"] is not None or packet["refusal"] != "ambiguous_cell":
            raise ValueError("Ambiguous original heading panel has chosen pixels")
        return None
    if packet["pixels"] is None:
        if packet["refusal"] not in {"pixel_budget", "region_budget"}:
            raise ValueError("Original heading panel has an unknown refusal")
        return None
    if packet["refusal"] is not None:
        raise ValueError("Refused original heading panel has pixel authority")
    # This is physical enclosure, not a text-inset/crop permission. Reuse the
    # four literal rule witnesses but retain ALL original pixels, including
    # corner interpolation and non-rule ink. No glyph is removed or recognized.
    return (
        cell
        if closed_cell_masks(packet["pixels"], cell, size, content_only=True)
        is not None
        else None
    )


def panel_page(page, heading, packet):
    """Keep a complete saved page; only the stop policy gets the owned lines."""
    cell = panel_bounds(packet, heading)
    if cell is None:
        return None, None, False
    lines = [line for line in page["lines"] if _intersects(line["bbox"], cell)]
    complete = all(inside_box(line["bbox"], cell) for line in lines)
    return cell, {**page, "lines": lines}, complete


def panel_candidate(box, lower, upper, cell):
    window = [cell[0], lower, cell[2], upper]
    return _intersects(box, window), inside_box(box, window)


def replay_panel(page, packet, heading):
    if panel_bounds(packet, heading) is None:
        raise ValueError("Unproved original heading panel cannot be replayed")
    for reading in packet["pixels"]["readings"]:
        replay_pixels(page, packet["pixels"]["bbox"], reading)
