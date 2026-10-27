"""Complete physical row partitions bound to original independent table columns."""

from .cell_frame_proof import inside_box
from .cell_raster import cell_pixel_rect
from .cell_text_limits import PHYSICAL_ROW_GAP
from .heading_source_geometry import MAX_HEADING_HEIGHT, MAX_HEADING_ROWS
from .title_context_grids import validate_parallel_title_grids


def _box(marks):
    return [
        min(b[0] for b in marks),
        min(b[1] for b in marks),
        max(b[2] for b in marks),
        max(b[3] for b in marks),
    ]


def _column_owns(mark, prefix, native_boxes, raster_boxes):
    if inside_box(mark, prefix):
        return True
    if tuple(mark) not in raster_boxes or tuple(mark) in native_boxes:
        return False
    # Retained raster marks are whole 400dpi pixels. The original geometric
    # column owns its floor/ceil pixel rectangle, not an invented point margin.
    pixels = cell_pixel_rect(prefix, 400)
    return inside_box(mark, [value * 72 / 400 for value in pixels])


def original_title_rows(
    marks, native, bounds, context, *, raster_marks=(), column_windows=None
):
    peers = validate_parallel_title_grids(context)
    groups, bottom = [], None
    for box in sorted(marks, key=lambda item: (item[1], item[0], item[3])):
        if bottom is not None and box[1] <= bottom + PHYSICAL_ROW_GAP:
            groups[-1].append(box)
            bottom = max(bottom, box[3])
        else:
            groups.append([box])
            bottom = box[3]
    native_boxes = {tuple(token["bbox"]) for token in native["tokens"]}
    raster_boxes = {tuple(box) for box in raster_marks}
    rows = []
    for group in groups:
        partitions = {None: group}
        if peers is not None:
            partitions, unowned = {}, False
            for mark in group:
                owners = [
                    index
                    for index, _grid in enumerate(peers)
                    if _column_owns(
                        mark, column_windows[index], native_boxes, raster_boxes
                    )
                ]
                if len(owners) != 1:
                    unowned = True
                    break
                partitions.setdefault(owners[0], []).append(mark)
            if unowned:
                partitions = {None: group}
        for owner in sorted(
            partitions, key=lambda value: -1 if value is None else value
        ):
            pieces = partitions[owner]
            ink = _box(pieces)
            box = (
                ink
                if peers is None
                else [
                    column_windows[owner][0] if owner is not None else bounds[0],
                    ink[1],
                    column_windows[owner][2] if owner is not None else bounds[2],
                    ink[3],
                ]
            )
            rows.append(
                {
                    "bbox": box,
                    "requires_read": any(
                        tuple(mark) not in native_boxes for mark in pieces
                    ),
                    **({"owner": owner, "ink_bbox": ink} if peers is not None else {}),
                }
            )
    unknown = [row for row in rows if row["requires_read"]]
    if len(unknown) > MAX_HEADING_ROWS:
        return [], "title_row_budget"
    if any(row["bbox"][3] - row["bbox"][1] > MAX_HEADING_HEIGHT for row in unknown):
        return [], "title_height_budget"
    return rows, None
