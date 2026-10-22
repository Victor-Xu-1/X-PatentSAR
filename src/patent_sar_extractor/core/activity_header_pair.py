"""Both original header views share one optional, unresolved-only auxiliary pass."""

from .activity_header_cells import (
    compose_header_column,
    empty_header_cell,
    header_leaf_cells,
    is_grid_column,
)
from .activity_header_columns import HeaderColumns
from .cell_raster import original_reading_image
from .text_ocr.cell_capture import refine_text_pair
from .text_ocr.configuration import get_auxiliary_text_runtime


def observe_header_pair(page, region, limit, tokens, observer):
    pair = [observer(page, region, limit, dpi, tokens) for dpi in (400, 600)]
    if all(all(view.verified) for view in pair):
        return pair
    auxiliary = get_auxiliary_text_runtime()
    if auxiliary is None:
        return pair
    if any(is_grid_column(column) for view in pair for column in view.columns):
        return _refine_grid_pair(page, pair, auxiliary)
    return _refine_columns(page, pair, auxiliary, limit)


def _refine_grid_pair(page, pair, auxiliary):
    children = [
        [list(header_leaf_cells(column)) for column in view.columns] for view in pair
    ]
    ys = pair[0].columns[0]["grid_ys"]
    if any(
        not is_grid_column(column) or column["grid_ys"] != ys
        for view in pair
        for column in view.columns
    ):
        raise ValueError("Paired original header-grid rows differ")
    refined = []
    for row in range(len(ys) - 1):
        physical_pair = []
        for view in children:
            cells = tuple(column[row] for column in view)
            physical_pair.append(
                HeaderColumns(
                    [[cell["raw_text"] for cell in cells]],
                    cells,
                    tuple(
                        empty_header_cell(cell)
                        or bool(cell.get("text"))
                        and not cell.get("crosses_boundary")
                        and not cell.get("detector_conflict")
                        for cell in cells
                    ),
                )
            )
        refined.append(_refine_columns(page, physical_pair, auxiliary, 1))
    result = []
    for view, dpi in enumerate((400, 600)):
        columns = tuple(
            compose_header_column(
                [row[view].columns[index] for row in refined], ys, index, dpi
            )
            for index in range(len(pair[view].columns))
        )
        result.append(
            HeaderColumns(
                [[""] * len(columns) for _ in range(len(ys) - 2)]
                + [[c["raw_text"] for c in columns]],
                columns,
                tuple(
                    bool(c["text"])
                    and not c["crosses_boundary"]
                    and not c["detector_conflict"]
                    for c in columns
                ),
            )
        )
    return result


def _refine_columns(page, pair, auxiliary, limit):
    columns = [list(view.columns) for view in pair]
    verified = [list(view.verified) for view in pair]
    if len(columns[0]) != len(columns[1]):
        raise ValueError("Original header column count differs across source views")
    for index, primaries in enumerate(zip(*columns)):
        if all(v[index] for v in verified) or any(
            p.get("crosses_boundary") or p.get("detector_conflict") for p in primaries
        ):
            continue
        if primaries[0].get("bbox") != primaries[1].get("bbox"):
            continue
        images = tuple(
            original_reading_image(page, p["bbox"], dpi, p)
            for p, dpi in zip(primaries, (400, 600))
        )
        attempts = []
        changed = refine_text_pair(images, primaries, auxiliary, evidence_sink=attempts)
        if changed is not None:
            for view, reading in enumerate(changed):
                columns[view][index] = {**reading, "detector_conflict": False}
                verified[view][index] = True
        elif attempts:
            for view, primary in enumerate(primaries):
                columns[view][index] = {**primary, "auxiliary_attempt": attempts[0]}
    return [
        HeaderColumns(
            [[""] * len(view_columns) for _ in range(limit - 1)]
            + [[c["raw_text"] for c in view_columns]],
            tuple(view_columns),
            tuple(view_verified),
        )
        for view_columns, view_verified in zip(columns, verified)
    ]
