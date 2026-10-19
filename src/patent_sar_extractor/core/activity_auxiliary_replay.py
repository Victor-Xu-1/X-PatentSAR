"""Original-pixel replay of auxiliary text; no OCR, model import, or saved paths."""

from collections.abc import Callable
from contextlib import AbstractContextManager
from functools import partial
from pathlib import Path

from patent_sar_extractor.contracts import AUXILIARY_TEXT_CELL_VERSION

from .activity_header_layout_proof import physical_discovery_views
from .cell_frame_proof import original_cell_frame_matches
from .source_evidence_identity import proof_id
from .text_ocr.cell_proof import replay_auxiliary_cell, valid_auxiliary_cell

OriginalReader = Callable[[], AbstractContextManager]
_MAX_ROWS = 2048
_MAX_SOURCE_CELLS = 16384


def original_pdf_reader(path: str | Path | None) -> OriginalReader | None:
    """Only a caller-owned original path is accepted, never a saved artifact path."""
    if path is None:
        return None
    import fitz

    return partial(fitz.open, path)


def auxiliary_columns(payload):
    """Yield bounded unique paired packets, after the shared header shape gate."""
    seen, rows = set(), {}
    for proof in payload.get("header_observations", {}).values():
        observed_columns = [
            *proof.get("observations", []),
            *(row for view in physical_discovery_views(proof) for row in view["rows"]),
        ]
        for observed in observed_columns:
            for column in observed.get("columns", []):
                physical = column.get("physical_header_lines")
                if "auxiliary_text" not in column and not (
                    isinstance(physical, dict)
                    and physical.get("version") == AUXILIARY_TEXT_CELL_VERSION
                ):
                    continue
                if not valid_auxiliary_cell(column, column.get("render_dpi")):
                    raise ValueError("Unproved auxiliary original text cell")
                page_no = proof.get("page_no")
                if type(page_no) is not int or not 1 <= page_no <= 20000:
                    raise ValueError("Missing auxiliary original page ownership")
                key = (
                    page_no,
                    proof_id(
                        {
                            "status": "auxiliary_text_observations",
                            "packet": column["auxiliary_text"],
                        }
                    ),
                )
                if key in seen:
                    continue
                seen.add(key)
                for view in column["auxiliary_text"]["views"]:
                    for row in view["rows"]:
                        observed = {
                            k: v
                            for k, v in row["observation"].items()
                            if k != "cache_hit"
                        }
                        identity = observed["model_fingerprint"], observed["id"]
                        if identity in rows and rows[identity] != observed:
                            raise ValueError(
                                "One auxiliary observation identity has conflicting outputs"
                            )
                        rows[identity] = observed
                if len(rows) > _MAX_ROWS or len(seen) > _MAX_SOURCE_CELLS:
                    raise ValueError(
                        "Auxiliary original row inventory exceeds its session bound"
                    )
                yield page_no, column


def original_discovery_columns(payload):
    """Primary/blank locator cells also need original pixels, not a saved flag."""
    seen = set()
    for proof in payload.get("header_observations", {}).values():
        for view in physical_discovery_views(proof):
            for row in view["rows"]:
                for column in row["columns"]:
                    if "auxiliary_text" in column:
                        continue  # The same auxiliary packet replayer covers it.
                    page_no = proof.get("page_no")
                    if type(page_no) is not int or not 1 <= page_no <= 20000:
                        raise ValueError("Missing original discovery page ownership")
                    key = (
                        page_no,
                        proof_id({"status": "original_locator_cell", "cell": column}),
                    )
                    if key not in seen:
                        seen.add(key)
                        if len(seen) > _MAX_SOURCE_CELLS:
                            raise ValueError(
                                "Original discovery cells exceed their bounded inventory"
                            )
                        yield page_no, column


def original_activity_source_errors(
    payload, *, open_original: OriginalReader | None = None
):
    """A saved consensus never substitutes for the actual immutable original."""
    columns = list(auxiliary_columns(payload))
    primary = list(original_discovery_columns(payload))
    if not columns and not primary:
        return []
    if open_original is None:
        return ["Original PDF is required for auxiliary activity text replay."]
    try:
        with open_original() as document:
            for page_no, column in primary:
                if page_no > len(document) or not original_cell_frame_matches(
                    column, document[page_no - 1]
                ):
                    return [
                        "Original discovery text differs from its original page pixels."
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
