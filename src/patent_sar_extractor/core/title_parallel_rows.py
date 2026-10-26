"""Complete physical row partitions bound to original independent table columns."""

from .cell_frame_proof import inside_box
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


def original_title_rows(marks, native, bounds, context):
    peers = validate_parallel_title_grids(context)
    if peers is not None and any(grid["ys"][0] != bounds[3] for grid in peers):
        return [], "parallel_title_window_conflict"
    groups, bottom = [], None
    for box in sorted(marks, key=lambda item: (item[1], item[0], item[3])):
        if bottom is not None and box[1] <= bottom + PHYSICAL_ROW_GAP:
            groups[-1].append(box)
            bottom = max(bottom, box[3])
        else:
            groups.append([box])
            bottom = box[3]
    native_boxes = {tuple(token["bbox"]) for token in native["tokens"]}
    rows = []
    for group in groups:
        partitions = {None: group}
        if peers is not None:
            partitions, unowned = {}, False
            for mark in group:
                owners = [
                    index
                    for index, grid in enumerate(peers)
                    if inside_box(
                        mark, [grid["xs"][0], bounds[1], grid["xs"][-1], bounds[3]]
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
                    peers[owner]["xs"][0] if owner is not None else bounds[0],
                    ink[1],
                    peers[owner]["xs"][-1] if owner is not None else bounds[2],
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
