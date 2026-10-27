"""Complete physical family windows and positively proved neighbour body cells."""

from itertools import pairwise

from .activity_context_geometry import context_floor, context_region, grid_box
from .cell_frame_proof import inside_box
from .source_geometry import overlaps
from .title_context_grids import MAX_TITLE_CELLS, validate_parallel_title_grids


def _ruling_span(grid, sources, size):
    from .source_cell_pixels import closed_cell_rule_span

    xs, ys = grid["xs"], grid["ys"]
    first, last = [xs[0], ys[0], xs[1], ys[1]], [xs[-2], ys[0], xs[-1], ys[1]]
    left = closed_cell_rule_span(sources[tuple(first)], first, size)
    right = (
        left
        if first == last
        else closed_cell_rule_span(sources[tuple(last)], last, size)
    )
    if left is None or right is None:
        raise ValueError("Original title columns have no paired rule extent")
    return [min(xs[0], left[0]), max(xs[-1], right[1])]


def family_column_spans(context, rulings, size):
    peers = validate_parallel_title_grids(context)
    if peers is None:
        return None
    sources = {tuple(r["cell"]): r["pixels"] for r in rulings}
    return [_ruling_span(grid, sources, size) for grid in peers]


def family_column_windows(context, spans=None):
    """Every peer keeps its own original preceding-table fence."""
    peers = validate_parallel_title_grids(context)
    if peers is None:
        return None
    boxes = [grid_box(grid) for grid in context["page_grids"]]
    return [
        [
            (spans[index] if spans is not None else grid["xs"])[0],
            context_floor(context_region(grid, boxes)["context_geometry"]),
            (spans[index] if spans is not None else grid["xs"])[-1],
            grid["ys"][0],
        ]
        for index, grid in enumerate(peers)
    ]


def family_title_bounds(context, bounds):
    peers = validate_parallel_title_grids(context)
    if peers is None:
        return list(bounds)
    windows = family_column_windows(context)
    return [
        0,
        min(window[1] for window in windows),
        bounds[2],
        max(window[3] for window in windows),
    ]


def family_body_cells(context, bounds):
    peers = validate_parallel_title_grids(context)
    if peers is None:
        return []
    cells = []
    for grid in context["page_grids"]:
        for top, bottom in pairwise(grid["ys"]):
            if top >= bounds[3]:
                break
            if bottom <= bounds[1]:
                continue
            for left, right in pairwise(grid["xs"]):
                if len(cells) >= MAX_TITLE_CELLS:
                    raise ValueError(
                        "Original title body cell inventory exceeds the grid bound"
                    )
                cells.append([left, top, right, bottom])
    return cells


def family_prior_regions(context, bounds, rulings, size):
    """Earlier title ink belongs only to an actually closed preceding frame.

    The complete family source is retained. This partitions an earlier scope,
    never a successful crop or an inferred page-half/nearest-title owner.
    A narrow preceding frame cannot hide ink outside its physical span.
    """
    if validate_parallel_title_grids(context) is None:
        return []
    windows = family_column_windows(
        context, family_column_spans(context, rulings, size)
    )
    sources = {tuple(r["cell"]): r["pixels"] for r in rulings}
    regions = set()
    for window in windows:
        if window[1] <= bounds[1]:
            continue
        for grid in context["page_grids"]:
            box = grid_box(grid)
            if (
                box[3] != window[1]
                or box[1] <= bounds[1]
                or min(box[2], window[2]) <= max(box[0], window[0])
            ):
                continue
            span = _ruling_span(grid, sources, size)
            regions.add(
                (max(span[0], window[0]), bounds[1], min(span[1], window[2]), box[1])
            )
    return [list(region) for region in sorted(regions)]


def title_marks_outside_bodies(marks, bodies):
    """Keep every non-body mark; clipping/crossing a proved cell is not ownership."""
    output = []
    for mark in marks:
        owners = [cell for cell in bodies if inside_box(mark, cell)]
        if len(owners) == 1:
            continue
        if owners or any(overlaps(mark, cell) for cell in bodies):
            return [], "crossing_title_body_ink"
        output.append(mark)
    return output, None


def native_title_context_complete(native, window, bodies):
    """Apply the existing glyph-completeness validator outside proved bodies.

    Raw observations/paints stay intact in the saved proof. Only complete native
    word and text-paint owners inside a positively proved cell are partitioned.
    Unowned/boundary/multi-cell text operations still fail the same validator.
    """
    from .native_window_coverage import native_window_text_complete
    from .source_geometry import SourceLayout, SourceTokens
    from .source_observations import source_cell_observation

    if bodies:
        tokens = [*native["tokens"], *native["boundary_tokens"]]
        by_paint = {}
        for token in tokens:
            if "native_paint" in token:
                by_paint.setdefault(token["native_paint"]["seqno"], []).append(token)

        def excluded_paint(paint):
            if paint["kind"] != "fill-text":
                return False
            if any(inside_box(paint["bbox"], cell) for cell in bodies):
                return True
            owned = by_paint.get(paint["seqno"], [])
            # Font operation boxes can overhang a word. Use the retained exact
            # paint identity and COMPLETE glyph sequence, never a point margin.
            return (
                bool(owned)
                and all(
                    token["native_paint"]["bbox"] == paint["bbox"]
                    and any(inside_box(token["bbox"], cell) for cell in bodies)
                    for token in owned
                )
                and "".join("".join(token["text"] for token in owned).split())
                == "".join(paint["text"].split())
            )

        kept = [
            token
            for token in tokens
            if not any(inside_box(token["bbox"], cell) for cell in bodies)
        ]
        native = source_cell_observation(
            SourceTokens(kept, SourceLayout(tuple(kept), None)),
            native["bbox"],
            native=True,
        )
        paints = [paint for paint in window["paints"] if not excluded_paint(paint)]
        window = {**window, "paints": paints, "paint_count": len(paints)}
    return not native["boundary_tokens"] and (
        native_window_text_complete(window, native)
        if native["tokens"]
        else not any(paint["kind"] == "fill-text" for paint in window["paints"])
    )
