"""Pure current header replay, not a second parser or confidence vote."""

import math
from itertools import pairwise

from .activity_header_identity import (
    compact_header,
    context_conflict,
    detector_header_conflict,
    header_conflict,
)
from .activity_header_sources import header_source_conflicts, select_header_context
from .activity_headers import context_from_text, grid_schema
from .cell_header_proof import physical_header_valid
from .cell_text_proof import valid_text_components


def _score(value):
    return type(value) in {int, float} and math.isfinite(value) and 0.85 <= value <= 1


def _column(column, index, header, band, dpi):
    if (
        not isinstance(column, dict)
        or type(column.get("physical_column")) is not int
        or column["physical_column"] != index
        or column.get("method") != f"cell_ocr_{dpi}dpi"
        or column.get("render_dpi") != dpi
        or type(column.get("render_dpi")) is not int
        or column.get("coordinate_space") != "original_pdf_points"
        or column.get("crosses_boundary") is not False
        or not _score(column.get("confidence"))
        or column.get("raw_text") != header
        or column.get("text") != header
        or not isinstance(column.get("native_text"), str)
        or header_conflict(column["native_text"], header)
    ):
        return False
    bounds, parts, detected = (
        column.get("bbox"),
        column.get("parts"),
        column.get("detection_parts"),
    )
    if (
        not isinstance(bounds, list)
        or len(bounds) != 4
        or any(
            type(value) not in {int, float} or not math.isfinite(value)
            for value in bounds
        )
        or not band[0] <= bounds[0] < bounds[2] <= band[2]
        or bounds[1:4:2] != band[1:4:2]
        or not isinstance(parts, list)
        or not 1 <= len(parts) <= 32
        or not isinstance(detected, list)
        or len(detected) > 32
        or any(
            not isinstance(part, dict)
            or not isinstance(part.get("text"), str)
            or len(part["text"]) > 4096
            for part in [*parts, *detected]
        )
        or any(not _score(part.get("confidence")) for part in parts)
        or column["confidence"] != min(part["confidence"] for part in parts)
    ):
        return False
    physical = "physical_header_lines" in column or any(
        part.get("method") == "physical_header_line" for part in parts
    )
    if physical:
        return (
            physical_header_valid(column)
            and column.get("detector_conflict") is False
            and not detector_header_conflict(detected, header)
        )
    if "single_row_readings" in column and not valid_text_components(column, dpi):
        return False
    return " ".join(part["text"] for part in parts) == header


def valid_header_proof(proof):
    """Recompute fields/units/columns/caption and original contradictions."""
    if type(proof.get("column_contract")) is not int or proof[
        "column_contract"
    ] not in {1, 2, 3, 4}:
        return False
    if proof["column_contract"] == 1 and "original_source" in proof:
        return False
    source = proof.get("original_source")
    source_version = source.get("schema_version") if isinstance(source, dict) else None
    if proof["column_contract"] == 2 and source_version in {2, 3}:
        return False
    if proof["column_contract"] == 3 and source_version != 2:
        return False
    if proof["column_contract"] == 4 and source_version != 3:
        return False
    if (
        proof.get("conflicting_columns") != []
        or proof.get("unverified_columns") != []
        or proof.get("context_conflict") is not False
    ):
        return False
    band, observations = proof.get("header_band_bbox"), proof.get("observations")
    if (
        not isinstance(band, list)
        or len(band) != 4
        or any(
            type(v) not in {int, float}
            or not math.isfinite(v)
            or not 0 <= v <= 1_000_000
            for v in band
        )
        or not band[0] < band[2]
        or not band[1] < band[3]
        or not isinstance(observations, list)
        or len(observations) != 2
    ):
        return False
    candidates = []
    for observed, dpi in zip(observations, (400, 600)):
        if (
            not isinstance(observed, dict)
            or observed.get("method") != f"header_ocr_{dpi}dpi"
            or not isinstance(observed.get("prefix"), str)
            or len(observed["prefix"]) > 10000
        ):
            return False
        matrix, columns = observed.get("matrix"), observed.get("columns")
        if (
            not isinstance(matrix, list)
            or not 1 <= len(matrix) <= 3
            or any(
                not isinstance(row, list)
                or not 2 <= len(row) <= 64
                or any(not isinstance(text, str) or len(text) > 4096 for text in row)
                for row in matrix
            )
            or any(len(row) != len(matrix[-1]) or any(row) for row in matrix[:-1])
            or not isinstance(columns, list)
            or len(columns) != len(matrix[-1])
            or any(
                not _column(column, i, matrix[-1][i], band, dpi)
                for i, column in enumerate(columns)
            )
            or columns[0]["bbox"][0] != band[0]
            or columns[-1]["bbox"][2] != band[2]
            or any(a["bbox"][2] != b["bbox"][0] for a, b in pairwise(columns))
        ):
            return False
        candidate = grid_schema(
            context_from_text(observed["prefix"], observed["prefix"]), matrix
        )
        if candidate is None or candidate.first_data_row != len(matrix):
            return False
        candidates.append(candidate)
    first, second = candidates
    if (
        tuple(map(compact_header, first.raw_headers))
        != tuple(map(compact_header, second.raw_headers))
        or first.first_data_row != second.first_data_row
        or tuple(g.id_column for g in first.groups)
        != tuple(g.id_column for g in second.groups)
        or not first.context.table_id
        and proof["column_contract"] not in {3, 4}
        or compact_header(first.context.raw_caption)
        != compact_header(second.context.raw_caption)
    ):
        return False
    originals, context = proof.get("original_headers"), proof.get("original_context")
    if (
        not isinstance(originals, list)
        or not isinstance(context, str)
        or len(context) > 100000
        or any(not isinstance(text, str) or len(text) > 4096 for text in originals)
    ):
        return False
    if originals:
        source = grid_schema(context_from_text(context, context), [originals])
        if (
            source is None
            or len(originals) != len(first.raw_headers)
            or tuple(g.id_column for g in source.groups)
            != tuple(g.id_column for g in first.groups)
        ):
            return False
        if proof["column_contract"] == 1 and any(
            context_conflict(source.context, candidate.context)
            or any(
                header_conflict(old, fresh)
                for old, fresh in zip(originals, candidate.raw_headers)
            )
            for candidate in candidates
        ):
            return False
    if proof["column_contract"] in {2, 3, 4}:
        for candidate in candidates:
            checked = header_source_conflicts(
                proof.get("original_source"), band, originals, context, candidate
            )
            if checked is None or any(checked[0]) or checked[1]:
                return False
        selected = select_header_context(proof["original_source"], band, first.context)
        if selected is None or proof.get("resolved_context") != selected.raw_context:
            return False
    return True
