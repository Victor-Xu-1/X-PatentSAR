"""An unresolved primary cell may request one bounded paired auxiliary observation."""

import copy

from patent_sar_extractor.core.cell_text_proof import valid_text_components
from patent_sar_extractor.core.ocsr.worker_process import WorkerProtocolError

from .cell_frames import source_rows
from .cell_proof import effective_cells
from .identity import recipe
from .process import TextOCRCancelled
from .protocol import frame_digest


def refine_text_pair(images, primaries, auxiliary, *, evidence_sink=None):
    if len(images) != 2 or len(primaries) != 2:
        raise ValueError("Auxiliary text requires both complete original views")
    if all(valid_text_components(p, dpi) for p, dpi in zip(primaries, (400, 600))):
        return None
    frames = [source_rows(image, dpi) for image, dpi in zip(images, (400, 600))]
    if any(frame is None for frame in frames):
        if evidence_sink is not None:
            evidence_sink.append(
                {"status": "not_attempted", "code": "unbounded_original_rows"}
            )
        return None
    views, fingerprint = [], None
    for dpi, frame, primary in zip((400, 600), frames, primaries):
        rows = []
        views.append(
            {
                **{k: v for k, v in frame.items() if k not in {"images", "row_bounds"}},
                "dpi": dpi,
                "primary": copy.deepcopy(primary),
                "rows": rows,
            }
        )
        try:
            for box, image in zip(frame["row_bounds"], frame["images"]):
                observed = auxiliary.observe(image)
                rows.append({"bbox": box, "observation": observed})
                if not isinstance(observed, dict) or observed.get(
                    "pixel_sha256"
                ) != frame_digest(image):
                    raise ValueError("Auxiliary source row identity differs")
                if fingerprint is None:
                    fingerprint = observed.get("model_fingerprint")
                if observed.get("model_fingerprint") != fingerprint:
                    raise ValueError("Auxiliary model identity changed")
        except TextOCRCancelled:
            raise
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
    packet = {
        "version": 1,
        "model": {
            "name": spec["model_name"],
            "revision": spec["model_revision"],
            "adapter_version": spec["adapter_version"],
            "fingerprint": fingerprint,
        },
        "views": views,
    }
    try:
        return effective_cells(packet)
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
