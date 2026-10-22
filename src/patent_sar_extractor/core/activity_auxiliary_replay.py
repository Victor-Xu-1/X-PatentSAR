"""Original activity text replay; no OCR, model import, or saved source paths."""

from collections.abc import Callable
from contextlib import AbstractContextManager
from functools import partial
from pathlib import Path

from .activity_header_cells import header_leaf_cells
from .activity_header_layout_proof import physical_discovery_views
from .activity_native_sources import original_native_contexts
from .activity_text_sources import declared_text_cells, original_text_pages_errors
from .cell_empty_proof import (
    EMPTY_GRID_METHOD,
    EMPTY_REGION_METHOD,
    replay_empty_source,
)
from .cell_frame_proof import original_cell_frame_matches
from .native_cell_replay import original_native_cell_matches
from .role_original_replay import original_role_source_errors
from .role_text_sources import role_text_cells
from .source_evidence_identity import proof_id
from .source_geometry import source_layout
from .source_paint_visibility import native_paint_view, visible_native_tokens
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
                for cell in header_leaf_cells(column):
                    yield proof.get("page_no"), cell
                    if "empty_source" in cell:
                        yield proof.get("page_no"), cell["empty_source"]
    for row in payload.get("rows", []):
        for source in row.get("activity_sources", []):
            yield from _row_text_cells(source)
    for source in payload.get("unresolved_rows", []):
        yield from _row_text_cells(source)
    yield from declared_text_cells(payload)


def _row_text_cells(source):
    for cell in source.get("cells", []):
        for reading in cell.get("observations", []):
            yield source.get("page_no"), reading


def _optical_cell(column):
    return str(column.get("method", "")).startswith("cell_ocr_") or any(
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


def original_primary_cells(payload):
    """One bounded ordinary native/optical inventory, including measured cells."""
    seen = set()
    for page_no, column in measurement_text_cells(payload):
        if has_auxiliary_text(column):
            continue  # The same auxiliary packet replayer covers it.
        if column.get("method") not in {
            "native_cell",
            EMPTY_GRID_METHOD,
            EMPTY_REGION_METHOD,
        } and not _optical_cell(column):
            continue  # Page-token locators do not become direct original reads.
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
    has_layouts = any(
        record.get("layout") or record.get("transposed_layout")
        for record in (payload.get("coverage") or {}).get("regions", [])
    ) or any(
        proof.get("original_source")
        for proof in payload.get("header_observations", {}).values()
    )
    has_declared = bool((payload.get("coverage") or {}).get("text_pages"))
    if (
        not columns
        and not primary
        and not role_sources
        and not has_layouts
        and not has_declared
    ):
        return []
    if open_original is None:
        return ["Original PDF is required for activity text replay."]
    layouts, paints = {}, {}
    try:
        with open_original() as document:
            text_errors = original_text_pages_errors(
                payload.get("coverage") or {}, document
            )
            if text_errors:
                return text_errors
            role_errors = original_role_source_errors(document, role_sources)
            if role_errors:
                return role_errors
            for page_no, packet, claims in original_native_contexts(
                payload, maximum=MAX_PRIMARY_SOURCE_CELLS
            ):
                if page_no > len(document):
                    return ["Original native context page is unavailable."]
                page = document[page_no - 1]
                if page_no not in layouts:
                    layouts[page_no] = source_layout(page)
                    paints[page_no] = native_paint_view(page)
                reading = {
                    "method": "native_cell",
                    "native_role": "witness",
                    "bbox": packet["bbox"],
                    "text": packet["text"],
                    "source_observation": packet,
                }
                if (
                    not original_native_cell_matches(
                        page,
                        reading,
                        layout=layouts[page_no],
                        paint_view=paints[page_no],
                    )
                    or claims
                    and not visible_native_tokens(
                        page, {"tokens": claims}, paint_view=paints[page_no]
                    )
                ):
                    return [
                        "Native activity header or context differs from its visible original source."
                    ]
            for page_no, column in primary:
                if page_no > len(document):
                    return ["Original activity cell page is unavailable."]
                page = document[page_no - 1]
                if column.get("method") in {EMPTY_GRID_METHOD, EMPTY_REGION_METHOD}:
                    if not replay_empty_source(page, column):
                        return [
                            "Original empty cell differs from its actual source pixels."
                        ]
                    continue
                if column.get("method") == "native_cell":
                    if page_no not in layouts:
                        layouts[page_no] = source_layout(page)
                        paints[page_no] = native_paint_view(page)
                    if not original_native_cell_matches(
                        page,
                        column,
                        layout=layouts[page_no],
                        paint_view=paints[page_no],
                    ):
                        return [
                            "Native activity text differs from its actual original source."
                        ]
                if _optical_cell(column) and not original_cell_frame_matches(
                    column, page
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
        return ["Original activity text replay is unavailable."]
    return []
