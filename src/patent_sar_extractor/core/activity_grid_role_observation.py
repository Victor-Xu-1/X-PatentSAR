"""Positive grid roles through the existing native/cell/coordinate OCR authority."""

from .activity_grid_context import table_matrix
from .activity_grid_role_proof import valid_role_scope
from .activity_grid_roles import (
    MAX_ROLE_CELLS,
    characterization_roles,
    declared_measurement,
    nominate_characterization,
)
from .cell_ocr_observation import observe_cell
from .page_ocr_cache import get_ocr_engine
from .source_geometry import native_cell_text, native_region
from .table_cells import cell_image


def observe_characterization(page, region, tokens, prefix):
    xs, ys = region["xs"], region["ys"]
    if (len(xs) - 1) * (len(ys) - 1) > MAX_ROLE_CELLS:
        return None
    # Cheap nomination never accepts a role; only complete original observations do.
    initial = table_matrix(tokens, region)
    if not nominate_characterization(initial, prefix):
        return None
    bounds = [xs[0], ys[0], xs[-1], ys[-1]]
    cells = [
        (xs[column], ys[row], xs[column + 1], ys[row + 1])
        for row in range(len(ys) - 1)
        for column in range(len(xs) - 1)
    ]
    hints = [
        [
            native_cell_text(tokens, cells[row * (len(xs) - 1) + column])
            for column in range(len(xs) - 1)
        ]
        for row in range(len(ys) - 1)
    ]
    if any(declared_measurement(text) for row in hints for text in row):
        return None
    observations = []
    if native_region(tokens, bounds, bool(page.get_text("words"))):
        observed = [
            {
                "method": "native_cell",
                "text": native_cell_text(tokens, cell),
                "bbox": list(cell),
            }
            for cell in cells
        ]
        observations.append(
            {"method": "native_cells", "matrix": hints, "cells": observed}
        )
    else:
        engine = get_ocr_engine()
        if not engine or engine[0] != "rapidocr":
            raise RuntimeError(
                "Original grid roles require the existing coordinate OCR engine"
            )
        for dpi in (400, 600):
            if any(
                max(0, cell[2] - cell[0] - 3)
                * max(0, cell[3] - cell[1] - 2.4)
                * (dpi / 72) ** 2
                > 8_000_000
                for cell in cells
            ):
                return None
            observed = [
                observe_cell(
                    cell_image(page, cell, dpi),
                    "header",
                    dpi,
                    engine[1],
                    lambda text, _kind: text,
                ).evidence(dpi, cell)
                for cell in cells
            ]
            matrix = [
                [
                    observed[row * (len(xs) - 1) + column]["text"]
                    for column in range(len(xs) - 1)
                ]
                for row in range(len(ys) - 1)
            ]
            observations.append(
                {"method": f"cell_ocr_{dpi}dpi", "matrix": matrix, "cells": observed}
            )
    roles = characterization_roles(observations[0]["matrix"], prefix)
    if roles is None:
        return None
    proof = {
        "version": 1,
        "xs": list(xs),
        "ys": list(ys),
        "prefix": prefix,
        "roles": roles,
        "native_hints": hints,
        "observations": observations,
    }
    return proof if valid_role_scope({"bbox": bounds, "role_scope": proof}) else None
