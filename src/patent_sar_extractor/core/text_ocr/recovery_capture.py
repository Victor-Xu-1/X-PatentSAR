"""Reuse the existing physical text observer with one literal auxiliary row adapter."""

import copy
import hashlib

from patent_sar_extractor.core.cell_header_lines import physical_line_frame
from patent_sar_extractor.core.cell_text_chunk_proof import MAX_TEXT_CHUNKS
from patent_sar_extractor.core.cell_text_chunks import observe_text_cell
from patent_sar_extractor.core.cell_text_scope import text_scope
from patent_sar_extractor.core.ocsr.worker_process import WorkerProtocolError

from .identity import recipe
from .process import TextOCRCancelled
from .recovery_primary import (
    PRIMARY_CONFLICT_CODE,
    complete_primary,
    primary_constraints_conflict,
    source_metadata,
)
from .recovery_proof import RECOVERY_VERSION, effective_recovery_cells
from .recovery_rows import RecoveryRowEngine, UnqualifiedRecoveryRow


def recover_complete_pair(
    images,
    primaries,
    auxiliary,
    *,
    maximum_rows=32,
    allow_chunks=True,
    maximum_row_height=12,
    evidence_sink=None,
):
    text_scope(maximum_rows, maximum_row_height)
    if (
        len(images) != 2
        or len(primaries) != 2
        or type(maximum_rows) is not int
        or not 2 <= maximum_rows <= 32
        or type(allow_chunks) is not bool
    ):
        raise ValueError("Invalid complete source recovery limits")
    if all(
        complete_primary(primary, dpi, maximum_row_height=maximum_row_height)
        for primary, dpi in zip(primaries, (400, 600), strict=True)
    ):
        return None
    if primary_constraints_conflict(primaries):
        if evidence_sink is not None:
            evidence_sink.append(
                {"status": "not_attempted", "code": PRIMARY_CONFLICT_CODE}
            )
        return None
    packet = capture_complete_views(
        images,
        primaries,
        auxiliary,
        maximum_rows=maximum_rows,
        allow_chunks=allow_chunks,
        maximum_row_height=maximum_row_height,
        evidence_sink=evidence_sink,
    )
    if packet is None:
        return None
    try:
        return effective_recovery_cells(packet)
    except (TypeError, ValueError, KeyError, IndexError):
        if evidence_sink is not None:
            evidence_sink.append(
                {
                    "status": "rejected",
                    "code": "unqualified_or_conflicting_rows",
                    "packet": packet,
                }
            )
        return None


def capture_complete_views(
    images,
    primaries,
    auxiliary,
    *,
    maximum_rows=32,
    allow_chunks=True,
    maximum_row_height=12,
    evidence_sink=None,
):
    """Capture raw source-owned observations, never grant a replacement policy.

    Generic text and narrowly typed title adapters validate their own unchanged
    original claims after this same bounded physical row capture.
    """
    text_scope(maximum_rows, maximum_row_height)
    if len(images) != 2 or len(primaries) != 2 or type(allow_chunks) is not bool:
        raise ValueError("Invalid complete source capture inventory")
    budget, views, fingerprint = [], [], None
    for image, primary, dpi in zip(images, primaries, (400, 600), strict=True):
        physical = physical_line_frame(
            image,
            0,
            dpi,
            maximum_rows=maximum_rows * (MAX_TEXT_CHUNKS if allow_chunks else 1),
            maximum_row_height=maximum_row_height,
        )
        if physical is not None and not physical["row_bounds"]:
            if evidence_sink is not None:
                evidence_sink.append(
                    {"status": "not_attempted", "code": "unbounded_original_rows"}
                )
            return None
        frame = {
            "dpi": dpi,
            "shape": list(image.shape),
            "pixel_sha256": hashlib.sha256(image.tobytes()).hexdigest(),
        }
        engine = RecoveryRowEngine(
            auxiliary=auxiliary, budget=budget, fingerprint=fingerprint
        )
        view = {
            "dpi": dpi,
            "primary": copy.deepcopy(primary),
            "frame": frame,
            "selected": None,
            "requests": engine.requests,
        }
        views.append(view)
        try:
            view["selected"] = {
                **source_metadata(primary),
                **observe_text_cell(
                    image,
                    dpi,
                    engine,
                    rows_per_chunk=maximum_rows,
                    maximum_row_height=maximum_row_height,
                ).evidence(dpi, primary["bbox"]),
            }
            view["selected"]["source_frame"] = frame
            fingerprint = engine.fingerprint
        except TextOCRCancelled:
            raise
        except UnqualifiedRecoveryRow:
            if evidence_sink is not None:
                evidence_sink.append(
                    {
                        "status": "rejected",
                        "code": "unqualified_original_row",
                        "views": views,
                    }
                )
            return None
        except (OSError, TimeoutError, WorkerProtocolError, ValueError) as error:
            if evidence_sink is not None:
                evidence_sink.append(
                    {
                        "status": "unavailable",
                        "code": "request_timeout"
                        if isinstance(error, TimeoutError)
                        else "runtime_or_source_failure",
                        "views": views,
                    }
                )
            return None
    spec = recipe()
    return {
        "version": RECOVERY_VERSION,
        "model": {
            "name": spec["model_name"],
            "revision": spec["model_revision"],
            "adapter_version": spec["adapter_version"],
            "fingerprint": fingerprint,
        },
        "views": views,
        "rows_per_chunk": maximum_rows,
        "allow_chunks": allow_chunks,
        "maximum_row_height": maximum_row_height,
    }
