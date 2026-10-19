"""Pure replay of complete original characterization-cell observations."""

import math

from patent_sar_extractor.contracts import CHARACTERIZATION_ROLE_SCHEMA_VERSION

from .activity_grid_roles import (
    MAX_ROLE_ROW_HEIGHT,
    MAX_ROLE_TEXT_ROWS,
    characterization_roles,
    declared_measurement,
)
from .activity_headers import context_from_text
from .cell_frame_proof import valid_cell_frame
from .cell_text_chunk_proof import text_detection_parts
from .cell_text_proof import valid_text_reading
from .cell_text_scope import text_scope
from .role_grid_windows import valid_role_windows


def valid_role_scope(record):
    proof = record.get("role_scope")
    if not isinstance(proof, dict) or set(proof) != {
        "version",
        "xs",
        "ys",
        "prefix",
        "roles",
        "native_hints",
        "observations",
    } | (
        {"work_windows"}
        if proof.get("version") in (2, 3, CHARACTERIZATION_ROLE_SCHEMA_VERSION)
        else set()
    ):
        return False
    if not valid_role_windows(proof):
        return False
    xs, ys = proof["xs"], proof["ys"]
    if record.get("bbox") != [xs[0], ys[0], xs[-1], ys[-1]]:
        return False
    rows, columns = len(ys) - 1, len(xs) - 1
    roles = proof["roles"]
    if (
        not isinstance(roles, dict)
        or set(roles) != {"data_start", "columns"}
        or type(roles["data_start"]) is not int
        or roles["data_start"] not in {0, 1}
        or not isinstance(roles["columns"], list)
        or len(roles["columns"]) != columns
        or any(
            type(role) is not str
            or role
            not in {"identifier", "preparation", "characterization", "nmr", "mass"}
            for role in roles["columns"]
        )
    ):
        return False
    hints = proof["native_hints"]
    if not isinstance(proof["prefix"], str) or len(proof["prefix"]) > 10000:
        return False
    if (
        "table_id" in record
        and context_from_text(proof["prefix"], proof["prefix"]).table_id
        != record["table_id"]
    ):
        return False
    if (
        not isinstance(hints, list)
        or len(hints) != rows
        or any(not isinstance(row, list) or len(row) != columns for row in hints)
        or any(
            not isinstance(text, str) or len(text) > 4096 or declared_measurement(text)
            for row in hints
            for text in row
        )
    ):
        return False
    observations = proof["observations"]
    if not isinstance(observations, list) or not 1 <= len(observations) <= 2:
        return False
    methods = []
    for observation in observations:
        if not isinstance(observation, dict) or set(observation) != {
            "method",
            "matrix",
            "cells",
        }:
            return False
        matrix, cells = observation["matrix"], observation["cells"]
        if (
            not isinstance(matrix, list)
            or len(matrix) != rows
            or not isinstance(cells, list)
            or len(cells) != rows * columns
            or characterization_roles(matrix, proof["prefix"]) != proof["roles"]
        ):
            return False
        method = observation["method"]
        if not isinstance(method, str):
            return False
        methods.append(method)
        for index, cell in enumerate(cells):
            row, column = divmod(index, columns)
            if (
                not isinstance(cell, dict)
                or cell.get("bbox")
                != [xs[column], ys[row], xs[column + 1], ys[row + 1]]
                or cell.get("text") != matrix[row][column]
            ):
                return False
            if method == "native_cells":
                if (
                    set(cell) != {"method", "text", "bbox"}
                    or cell.get("method") != "native_cell"
                    or cell["text"] != hints[row][column]
                ):
                    return False
            elif method in {"cell_ocr_400dpi", "cell_ocr_600dpi"}:
                confidence = cell.get("confidence")
                if proof[
                    "version"
                ] == CHARACTERIZATION_ROLE_SCHEMA_VERSION and cell.get(
                    "text_scope"
                ) != text_scope(MAX_ROLE_TEXT_ROWS, MAX_ROLE_ROW_HEIGHT):
                    return False
                if (
                    set(cell)
                    - {
                        "physical_header_lines",
                        "physical_text_chunks",
                        "single_row_readings",
                        *(
                            {"text_scope"}
                            if proof["version"] == CHARACTERIZATION_ROLE_SCHEMA_VERSION
                            else set()
                        ),
                        *(
                            {
                                "source_frame",
                                "auxiliary_text",
                                "auxiliary_text_version",
                                "auxiliary_text_attempts",
                                "detector_conflict",
                            }
                            if proof["version"]
                            in (3, CHARACTERIZATION_ROLE_SCHEMA_VERSION)
                            else set()
                        ),
                    }
                    != {
                        "method",
                        "text",
                        "raw_text",
                        "confidence",
                        "parts",
                        "bbox",
                        "coordinate_space",
                        "ink_crop_pixels",
                        "border_pixels",
                        "render_dpi",
                        "detection_parts",
                    }
                    or cell.get("method") != method
                    or type(confidence) not in {int, float}
                    or not 0.85 <= confidence <= 1
                    or not math.isfinite(confidence)
                    or cell.get("coordinate_space") != "original_pdf_points"
                    or cell.get("render_dpi") != int(method[9:12])
                    or cell.get("detector_conflict", False) is not False
                    or proof["version"] == CHARACTERIZATION_ROLE_SCHEMA_VERSION
                    and not valid_cell_frame(
                        cell.get("source_frame"), cell, cell["bbox"], int(method[9:12])
                    )
                    or not isinstance(cell.get("raw_text"), str)
                    or cell["raw_text"] != cell["text"]
                    or not isinstance(cell.get("parts"), list)
                    or not cell.get("parts")
                    and "physical_text_chunks" not in cell
                    or len(cell["parts"]) > 32
                    or not isinstance(cell.get("detection_parts"), list)
                    or len(cell["detection_parts"]) > 32
                ):
                    return False
                if any(
                    not isinstance(part, dict)
                    or not isinstance(part.get("text"), str)
                    or type(part.get("confidence")) not in {int, float}
                    or not 0.85 <= part["confidence"] <= 1
                    or not math.isfinite(part["confidence"])
                    for part in cell["parts"]
                ):
                    return False
                if not valid_text_reading(
                    cell,
                    cell["bbox"],
                    int(method[9:12]),
                    maximum_rows=MAX_ROLE_TEXT_ROWS,
                    maximum_row_height=MAX_ROLE_ROW_HEIGHT
                    if proof["version"] == CHARACTERIZATION_ROLE_SCHEMA_VERSION
                    else 12,
                    allow_chunks=True,
                ):
                    return False
                if any(
                    not isinstance(part, dict)
                    or set(part)
                    - {"text", "confidence", "bbox", "coordinate_space", "method"}
                    or not isinstance(part.get("text"), str)
                    or len(part["text"]) > 4096
                    or type(part.get("confidence")) not in {int, float}
                    or not 0 <= part["confidence"] <= 1
                    or not math.isfinite(part["confidence"])
                    or part["confidence"] >= 0.85
                    and declared_measurement(part["text"])
                    for part in text_detection_parts(cell)
                ):
                    return False
            else:
                return False
    return methods == ["native_cells"] or methods == [
        "cell_ocr_400dpi",
        "cell_ocr_600dpi",
    ]
