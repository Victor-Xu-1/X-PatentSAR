"""Original-pixel replay of auxiliary text; no OCR, model import, or saved paths."""

from collections.abc import Callable
from contextlib import AbstractContextManager
from functools import partial
from pathlib import Path

from .activity_header_layout_proof import physical_discovery_views
from .cell_frame_proof import original_cell_frame_matches
from .role_original_replay import original_role_source_errors
from .role_text_sources import role_text_cells
from .source_evidence_identity import proof_id
from .text_ocr.cell_proof import has_auxiliary_text, replay_auxiliary_cell
from .text_ocr.source_inventory import auxiliary_source_cells

# Ordinary observations cover the full dataset, unlike sparse auxiliary rescue.
# This bounds replay work without reusing the smaller model-request inventory.
MAX_PRIMARY_SOURCE_CELLS = 1_000_000

OriginalReader = Callable[[], AbstractContextManager]


def original_pdf_reader(path: str | Path | None) -> OriginalReader | None:
    """Only a caller-owned original path is accepted, never a saved artifact path."""
    if path is None:
        return None
    import fitz

    return partial(fitz.open, path)


def auxiliary_columns(payload):
    """Headers and actual row cells share one original observation inventory."""
    return auxiliary_source_cells(activity_text_cells(payload))


def activity_text_cells(payload):
    yield from measurement_text_cells(payload)
    yield from role_text_cells(payload)


def measurement_text_cells(payload):
    """One inventory for locator/final headers and accepted/unresolved row cells."""
    for proof in payload.get("header_observations", {}).values():
        observed_columns = [
            *proof.get("observations", []),
            *(row for view in physical_discovery_views(proof) for row in view["rows"]),
        ]
        for observed in observed_columns:
            for column in observed.get("columns", []):
                yield proof.get("page_no"), column
    for row in payload.get("rows", []):
        for source in row.get("activity_sources", []):
            yield from _row_text_cells(source)
    for source in payload.get("unresolved_rows", []):
        yield from _row_text_cells(source)


def _row_text_cells(source):
    for cell in source.get("cells", []):
        for reading in cell.get("observations", []):
            yield source.get("page_no"), reading


def original_primary_cells(payload):
    """All ordinary optical cells need source pixels, not only header locators."""
    seen = set()
    for page_no, column in measurement_text_cells(payload):
        if has_auxiliary_text(column):
            continue  # The same auxiliary packet replayer covers it.
        if not (
            str(column.get("method", "")).startswith("cell_ocr_")
            or any(
                name in column
                for name in (
                    "render_dpi",
                    "source_frame",
                    "physical_header_lines",
                    "physical_text_chunks",
                    "ink_crop_pixels",
                    "single_row_readings",
                )
            )
        ):
            continue  # Native/page-token observations do not become optical reads.
        if type(page_no) is not int or not 1 <= page_no <= 20000:
            raise ValueError("Missing original activity cell page ownership")
        key = page_no, proof_id({"status": "original_activity_cell", "cell": column})
        if key not in seen:
            seen.add(key)
            if len(seen) > MAX_PRIMARY_SOURCE_CELLS:
                raise ValueError(
                    "Original activity cells exceed their bounded inventory"
                )
            yield page_no, column


def original_activity_source_errors(
    payload, *, open_original: OriginalReader | None = None
):
    """A saved consensus never substitutes for the actual immutable original."""
    columns = list(auxiliary_columns(payload))
    primary = list(original_primary_cells(payload))
    role_sources = list(role_text_cells(payload))
    if not columns and not primary and not role_sources:
        return []
    if open_original is None:
        return ["Original PDF is required for activity text replay."]
    try:
        with open_original() as document:
            role_errors = original_role_source_errors(document, role_sources)
            if role_errors:
                return role_errors
            for page_no, column in primary:
                if page_no > len(document) or not original_cell_frame_matches(
                    column, document[page_no - 1]
                ):
                    return [
                        "Original activity cell differs from its original page pixels."
                    ]
            for page_no, column in columns:
                if page_no > len(document) or not replay_auxiliary_cell(
                    column, document[page_no - 1]
                ):
                    return [
                        "Auxiliary activity text differs from its original page pixels."
                    ]
    except (OSError, ValueError, TypeError, KeyError, IndexError, RuntimeError):
        return ["Auxiliary activity text original replay is unavailable."]
    return []
