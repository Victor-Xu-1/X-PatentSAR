"""Positive grid roles through the existing native/cell/coordinate OCR authority."""

import hashlib
from itertools import pairwise

import numpy as np

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
from .table_cells import CellRenderLimit, cell_image


def observe_role_cells(page, region, tokens, *, retain_frames=False):
    """One cell observation carrier for closed grids and visible row fragments."""
    xs, ys = region["xs"], region["ys"]
    if (len(xs) - 1) * (len(ys) - 1) > MAX_ROLE_CELLS:
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
    observations = []
    frames = []
    native = native_region(tokens, bounds, bool(page.get_text("words")))
    if native and retain_frames:
        for index, cell in enumerate(cells):
            row, column = divmod(index, len(xs) - 1)
            if not hints[row][column].strip():
                try:
                    image = cell_image(page, cell, 400)
                except CellRenderLimit:
                    return None
                if np.any(image < 180):
                    native = False
                    break
    if native:
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
            observed, rendered = [], []
            for cell in cells:
                try:
                    image = cell_image(page, cell, dpi)
                except CellRenderLimit:
                    return None
                observed.append(
                    observe_cell(
                        image,
                        "header",
                        dpi,
                        engine[1],
                        lambda text, _kind: text,
                    ).evidence(dpi, cell)
                )
                if retain_frames:
                    rendered.append(
                        {
                            "dpi": dpi,
                            "shape": list(image.shape),
                            "pixel_sha256": hashlib.sha256(image).hexdigest(),
                        }
                    )
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
            if retain_frames:
                frames.append(rendered)
    return {
        "xs": list(xs),
        "ys": list(ys),
        "native_hints": hints,
        "observations": observations,
        **({"rendered_frames": frames} if retain_frames else {}),
    }


def observe_characterization(page, region, tokens, prefix):
    # Cheap nomination never accepts a role; only complete original observations do.
    xs, ys = region["xs"], region["ys"]
    if (len(xs) - 1) * (len(ys) - 1) > MAX_ROLE_CELLS:
        return None
    initial = table_matrix(tokens, region)
    if not nominate_characterization(initial, prefix):
        return None
    if any(
        declared_measurement(native_cell_text(tokens, (x0, y0, x1, y1)))
        for x0, x1 in pairwise(xs)
        for y0, y1 in pairwise(ys)
    ):
        return None
    cells = observe_role_cells(page, region, tokens)
    if cells is None:
        return None
    observations = cells["observations"]
    roles = characterization_roles(observations[0]["matrix"], prefix)
    if roles is None:
        return None
    proof = {
        "version": 1,
        **cells,
        "prefix": prefix,
        "roles": roles,
    }
    bounds = [xs[0], ys[0], xs[-1], ys[-1]]
    return proof if valid_role_scope({"bbox": bounds, "role_scope": proof}) else None
