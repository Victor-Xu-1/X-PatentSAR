"""Qualified original context and physical frames; no column/ID inference."""

from .activity_context_geometry import grid_box, validate_grid_axes
from .activity_continuation_policy import continuation_prefix
from .printed_identifiers import identifier_key
from .source_cell_tokens import cell_lines, cell_text
from .source_window_chunks import validate_source_window, window_source_tokens


def validate_page_grid(grid, size):
    if (
        not isinstance(grid, dict)
        or set(grid) != {"xs", "ys"}
        or any(
            not isinstance(grid[name], list) or len(grid[name]) < 2
            for name in ("xs", "ys")
        )
    ):
        raise ValueError("Malformed original continuation grid")
    validate_grid_axes(grid, grid_box(grid))
    if not (
        0 <= grid["xs"][0] < grid["xs"][-1] <= size[0]
        and 0 <= grid["ys"][0] < grid["ys"][-1] <= size[1]
    ):
        raise ValueError("Original continuation grid leaves its page")


def qualified_running_window(chunks, window, xs, pairs):
    """Running page text cannot hide an unowned ID, section or weak source."""
    if window[1] == window[3]:
        return chunks == []
    validate_source_window(chunks, window)
    if any(
        p["text"].strip() and p["status"] != "qualified"
        for chunk in chunks
        for p in chunk["sources"]
    ):
        return False
    for native in (False, True):
        tokens = window_source_tokens(chunks, window, native=native)
        if not continuation_prefix(cell_text(tokens, window)):
            return False
        for identifier, _structure in pairs:
            column = [xs[identifier], window[1], xs[identifier + 1], window[3]]
            if any(
                identifier_key(
                    cell_text(line, column), wrapped=True, terminal_period=True
                )
                for line in cell_lines(tokens, column)
            ):
                return False
    return True
