"""Physical grid rows compose a column, never synthesize a whole-band OCR read."""

import math
from itertools import pairwise

from .cell_empty_proof import (
    observe_empty_grid_cell,
    observe_empty_text_region,
    valid_empty_source,
)
from .cell_frame_proof import valid_cell_frame

GRID_METHOD = "header_grid_column_"
MAX_HEADER_GRID_ROWS = 3


def is_grid_column(column):
    return isinstance(column, dict) and (
        str(column.get("method", "")).startswith(GRID_METHOD)
        or "header_cells" in column
        or "grid_ys" in column
    )


def header_leaf_cells(column):
    """Only explicit bounded physical children, never an arbitrary recursive scan."""
    if not is_grid_column(column):
        yield column
        return
    try:
        cells, ys, bounds = column["header_cells"], column["grid_ys"], column["bbox"]
        dpi, index = column["render_dpi"], column["physical_column"]
        if (
            type(dpi) is not int
            or dpi not in {400, 600}
            or column["method"] != f"{GRID_METHOD}{dpi}dpi"
            or type(index) is not int
            or not 0 <= index < 64
            or not isinstance(cells, list)
            or not 2 <= len(cells) <= MAX_HEADER_GRID_ROWS
            or not isinstance(ys, list)
            or len(ys) != len(cells) + 1
            or any(type(v) not in {int, float} or not math.isfinite(v) for v in ys)
            or any(b <= a for a, b in pairwise(ys))
            or not isinstance(bounds, list)
            or len(bounds) != 4
            or bounds[1::2] != [ys[0], ys[-1]]
        ):
            raise ValueError("Malformed original header-grid column")
        for row, cell in enumerate(cells):
            if (
                not isinstance(cell, dict)
                or is_grid_column(cell)
                or cell.get("method") != f"cell_ocr_{dpi}dpi"
                or cell.get("render_dpi") != dpi
                or type(cell.get("physical_column")) is not int
                or cell["physical_column"] != index
                or cell.get("bbox") != [bounds[0], ys[row], bounds[2], ys[row + 1]]
            ):
                raise ValueError("Original header-grid child lost its physical owner")
        yield from cells
    except (KeyError, TypeError, IndexError, OverflowError) as error:
        raise ValueError("Malformed original header-grid source") from error


def empty_header_cell(cell):
    proof = cell.get("empty_source")
    return (
        isinstance(proof, dict)
        and valid_empty_source(proof)
        and proof["bbox"] == cell.get("bbox")
        and cell.get("text") == cell.get("raw_text") == ""
        and cell.get("parts") == cell.get("detection_parts") == []
        and not str(cell.get("native_text", "")).strip()
        and cell.get("crosses_boundary") is False
        and valid_cell_frame(
            cell.get("source_frame"), cell, cell["bbox"], cell.get("render_dpi")
        )
    )


def retain_header_absence(page, cell):
    """A blank physical header child needs the existing paired absence proof."""
    if (
        cell.get("text") == cell.get("raw_text") == ""
        and cell.get("parts") == cell.get("detection_parts") == []
        and not cell.get("native_text")
        and cell.get("crosses_boundary") is False
    ):
        proof = observe_empty_grid_cell(page, cell["bbox"])
        if proof is None:
            proof = observe_empty_text_region(page, cell["bbox"])
        if proof is not None:
            return {**cell, "empty_source": proof}
    return cell


def compose_header_column(cells, ys, index, dpi):
    """Conserve every child observation, including rejected and proved-empty rows."""
    raw = "\n".join(cell["raw_text"] for cell in cells if cell["raw_text"])
    nonempty = [cell for cell in cells if cell["raw_text"]]
    qualified = bool(nonempty) and all(
        bool(cell.get("text"))
        and cell.get("text") == cell.get("raw_text")
        or empty_header_cell(cell)
        for cell in cells
    )
    return {
        "method": f"{GRID_METHOD}{dpi}dpi",
        "render_dpi": dpi,
        "coordinate_space": "original_pdf_points",
        "physical_column": index,
        "bbox": [cells[0]["bbox"][0], ys[0], cells[0]["bbox"][2], ys[-1]],
        "grid_ys": list(ys),
        "header_cells": cells,
        "raw_text": raw,
        "text": raw if qualified else "",
        "confidence": min((cell["confidence"] for cell in nonempty), default=0.0),
        "native_text": "\n".join(
            cell["native_text"] for cell in cells if cell["native_text"]
        ),
        "crosses_boundary": any(cell.get("crosses_boundary") for cell in cells),
        "detector_conflict": any(cell.get("detector_conflict") for cell in cells),
    }


def valid_header_grid_column(column, index, header, band, dpi, validate_leaf):
    try:
        cells = list(header_leaf_cells(column))
        expected = compose_header_column(cells, column["grid_ys"], index, dpi)
        if column != expected or column["text"] != header or not header:
            return False
        if (
            column["physical_column"] != index
            or column["render_dpi"] != dpi
            or not band[0] <= column["bbox"][0] < column["bbox"][2] <= band[2]
            or column["bbox"][1::2] != band[1::2]
            or column["coordinate_space"] != "original_pdf_points"
            or column["crosses_boundary"]
            or column["detector_conflict"]
        ):
            return False
        return all(
            empty_header_cell(cell)
            if "empty_source" in cell
            else validate_leaf(
                cell,
                index,
                cell["raw_text"],
                [band[0], cell["bbox"][1], band[2], cell["bbox"][3]],
                dpi,
            )
            for cell in cells
        )
    except (KeyError, TypeError, ValueError, IndexError, OverflowError):
        return False
