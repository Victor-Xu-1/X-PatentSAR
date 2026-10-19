"""Positive grid roles through the existing native/cell/coordinate OCR authority."""

import hashlib
from itertools import pairwise

import numpy as np

from patent_sar_extractor.contracts import CHARACTERIZATION_ROLE_SCHEMA_VERSION

from .activity_grid_context import table_matrix
from .activity_grid_role_proof import valid_role_scope
from .activity_grid_roles import (
    MAX_ROLE_TEXT_ROWS,
    characterization_roles,
    declared_measurement,
    nominate_characterization,
)
from .cell_text_chunks import observe_text_cell
from .page_ocr_cache import get_ocr_engine
from .role_grid_windows import MAX_ROLE_CELLS, role_grid_shape, role_work_windows
from .source_geometry import native_cell_text, native_region
from .source_role_observations import role_failure
from .table_cells import CellRenderLimit, cell_image


def observe_role_cells(
    page,
    region,
    tokens,
    *,
    retain_frames=False,
    attach_source_frames=False,
    evidence_sink=None,
    maximum_row_height=12,
):
    """One cell observation carrier for closed grids and visible row fragments."""
    xs, ys = region["xs"], region["ys"]
    bounds = [xs[0], ys[0], xs[-1], ys[-1]]
    return _observe_role_cells(
        page,
        region,
        tokens,
        native=native_region(tokens, bounds, bool(page.get_text("words"))),
        retain_frames=retain_frames,
        attach_source_frames=attach_source_frames,
        evidence_sink=evidence_sink,
        maximum_row_height=maximum_row_height,
    )


def _observe_role_cells(
    page,
    region,
    tokens,
    *,
    native,
    retain_frames=False,
    attach_source_frames=False,
    evidence_sink=None,
    maximum_row_height=12,
):
    """Same observer with the original parent's source decision conserved."""
    xs, ys = region["xs"], region["ys"]
    if (len(xs) - 1) * (len(ys) - 1) > MAX_ROLE_CELLS:
        return None
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
    carrier = {
        "xs": list(xs),
        "ys": list(ys),
        "native_hints": hints,
        "observations": observations,
        **({"rendered_frames": frames} if retain_frames else {}),
    }
    if evidence_sink is not None:
        evidence_sink.append(carrier)
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
            observation = {
                "method": f"cell_ocr_{dpi}dpi",
                "matrix": [],
                "cells": observed,
            }
            observations.append(observation)
            if retain_frames:
                frames.append(rendered)
            for cell in cells:
                try:
                    image = cell_image(page, cell, dpi)
                except CellRenderLimit:
                    return None
                reading = observe_text_cell(
                    image,
                    dpi,
                    engine[1],
                    rows_per_chunk=MAX_ROLE_TEXT_ROWS,
                    maximum_row_height=maximum_row_height,
                ).evidence(dpi, cell)
                if retain_frames or attach_source_frames:
                    frame = {
                        "dpi": dpi,
                        "shape": list(image.shape),
                        "pixel_sha256": hashlib.sha256(image).hexdigest(),
                    }
                    if attach_source_frames:
                        reading["source_frame"] = frame
                    if retain_frames:
                        rendered.append(frame)
                observed.append(reading)
            matrix = [
                [
                    observed[row * (len(xs) - 1) + column]["text"]
                    for column in range(len(xs) - 1)
                ]
                for row in range(len(ys) - 1)
            ]
            observation["matrix"] = matrix
    return carrier


def observe_characterization(page, region, tokens, prefix, *, evidence_sink=None):
    # Cheap nomination never accepts a role; only complete original observations do.
    xs, ys = region["xs"], region["ys"]

    def refused(reason, cells=None):
        if evidence_sink is not None:
            evidence_sink.append(role_failure(reason, region, prefix, cells))

    if role_grid_shape(list(xs), list(ys)) is None:
        return refused("cell_budget_exceeded")
    initial = table_matrix(tokens, region)
    if not nominate_characterization(initial, prefix):
        return None
    if any(
        declared_measurement(native_cell_text(tokens, (x0, y0, x1, y1)))
        for x0, x1 in pairwise(xs)
        for y0, y1 in pairwise(ys)
    ):
        return refused("native_measurement_conflict")
    attempted = []
    from .role_grid_capture import observe_complete_role_grid

    cells = observe_complete_role_grid(page, region, tokens, evidence_sink=attempted)
    if cells is None:
        return refused("cell_render_limit", attempted[0] if attempted else None)
    from .role_text_capture import refine_role_text

    refine_role_text(page, cells)
    observations = cells["observations"]
    roles = characterization_roles(observations[0]["matrix"], prefix)
    if roles is None:
        return refused("unresolved_column_roles", cells)
    proof = {
        "version": CHARACTERIZATION_ROLE_SCHEMA_VERSION,
        **cells,
        "work_windows": role_work_windows(list(xs), list(ys)),
        "prefix": prefix,
        "roles": roles,
    }
    bounds = [xs[0], ys[0], xs[-1], ys[-1]]
    return (
        proof
        if valid_role_scope({"bbox": bounds, "role_scope": proof})
        else refused("unqualified_role_observations", cells)
    )
