"""Unresolved complete role cells use the shared paired original-text recovery."""

from .activity_grid_roles import MAX_ROLE_ROW_HEIGHT, MAX_ROLE_TEXT_ROWS
from .role_grid_windows import role_grid_shape
from .text_ocr.source_capture import refine_source_text


def refine_role_text(page, cells):
    shape = role_grid_shape(cells["xs"], cells["ys"])
    views = cells["observations"]
    if shape is None:
        raise ValueError("Invalid original role-text recovery inventory")
    if [view["method"] for view in views] == ["native_cells"]:
        return
    if [view["method"] for view in views] != ["cell_ocr_400dpi", "cell_ocr_600dpi"]:
        raise ValueError("Incomplete original role-text recovery views")
    rows, width = shape
    for index in range(rows * width):
        row, column = divmod(index, width)
        bounds = [
            cells["xs"][column],
            cells["ys"][row],
            cells["xs"][column + 1],
            cells["ys"][row + 1],
        ]
        readings = [view["cells"][index] for view in views]
        if any(reading.get("bbox") != bounds for reading in readings):
            raise ValueError("Role text recovery cannot move a physical source cell")
        selected = refine_source_text(
            page,
            bounds,
            readings,
            maximum_rows=MAX_ROLE_TEXT_ROWS,
            allow_chunks=True,
            maximum_row_height=MAX_ROLE_ROW_HEIGHT,
        )
        for view, reading in zip(views, selected, strict=True):
            view["cells"][index] = reading
            view["matrix"][row][column] = reading["text"]
