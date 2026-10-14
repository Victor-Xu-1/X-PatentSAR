"""Pure replay of complete original characterization-cell observations."""

import math
from itertools import pairwise

from .activity_grid_roles import (
    MAX_ROLE_CELLS,
    characterization_roles,
    declared_measurement,
)
from .activity_headers import context_from_text


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
    }:
        return False
    if type(proof["version"]) is not int or proof["version"] != 1:
        return False
    xs, ys = proof["xs"], proof["ys"]
    if any(
        not isinstance(edges, list)
        or len(edges) < 2
        or len(edges) > MAX_ROLE_CELLS + 1
        or any(
            type(value) not in {int, float}
            or not math.isfinite(value)
            or not 0 <= value <= 100000
            for value in edges
        )
        or any(b <= a for a, b in pairwise(edges))
        for edges in (xs, ys)
    ) or record.get("bbox") != [xs[0], ys[0], xs[-1], ys[-1]]:
        return False
    rows, columns = len(ys) - 1, len(xs) - 1
    if rows * columns > MAX_ROLE_CELLS:
        return False
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
                if (
                    set(cell)
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
                    or not math.isfinite(confidence)
                    or not 0.85 <= confidence <= 1
                    or cell.get("coordinate_space") != "original_pdf_points"
                    or cell.get("render_dpi") != int(method[9:12])
                    or not isinstance(cell.get("raw_text"), str)
                    or cell["raw_text"] != cell["text"]
                    or not isinstance(cell.get("parts"), list)
                    or not cell.get("parts")
                    or len(cell["parts"]) > 32
                    or not isinstance(cell.get("detection_parts"), list)
                    or len(cell["detection_parts"]) > 32
                ):
                    return False
                if any(
                    not isinstance(part, dict)
                    or not isinstance(part.get("text"), str)
                    or type(part.get("confidence")) not in {int, float}
                    or not math.isfinite(part["confidence"])
                    or not 0.85 <= part["confidence"] <= 1
                    for part in cell["parts"]
                ):
                    return False
                if " ".join(part["text"] for part in cell["parts"]) != cell["raw_text"]:
                    return False
                if any(
                    not isinstance(part, dict)
                    or set(part)
                    - {"text", "confidence", "bbox", "coordinate_space", "method"}
                    or not isinstance(part.get("text"), str)
                    or len(part["text"]) > 4096
                    or type(part.get("confidence")) not in {int, float}
                    or not math.isfinite(part["confidence"])
                    or not 0 <= part["confidence"] <= 1
                    or part["confidence"] >= 0.85
                    and declared_measurement(part["text"])
                    for part in cell["detection_parts"]
                ):
                    return False
            else:
                return False
    return methods == ["native_cells"] or methods == [
        "cell_ocr_400dpi",
        "cell_ocr_600dpi",
    ]
