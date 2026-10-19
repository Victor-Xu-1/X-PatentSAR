"""Complete recovered observations over retained primary views and original rows."""

import hashlib
import re

from patent_sar_extractor.contracts import (
    AUXILIARY_TEXT_CELL_VERSION,
    AUXILIARY_TEXT_RECOVERY_VERSION,
)
from patent_sar_extractor.core.cell_text_chunks import observe_text_cell
from patent_sar_extractor.core.cell_text_proof import valid_text_reading

from .cell_frames import literal
from .identity import recipe
from .recovery_primary import compatible_primary, parts, source_metadata
from .recovery_rows import RecoveryRowEngine, checked_group, checked_row

RECOVERY_VERSION = AUXILIARY_TEXT_RECOVERY_VERSION


def effective_recovery_cells(packet):
    if (
        not isinstance(packet, dict)
        or set(packet)
        != {"version", "model", "views", "rows_per_chunk", "allow_chunks"}
        or type(packet["version"]) is not int
        or packet["version"] not in (2, RECOVERY_VERSION)
    ):
        raise ValueError("Unknown complete auxiliary recovery evidence")
    maximum, allow = packet["rows_per_chunk"], packet["allow_chunks"]
    model, spec, views = packet["model"], recipe(), packet["views"]
    if (
        type(maximum) is not int
        or not 2 <= maximum <= 32
        or type(allow) is not bool
        or not isinstance(model, dict)
        or set(model) != {"name", "revision", "adapter_version", "fingerprint"}
        or any(
            model[key] != spec[source]
            for key, source in (
                ("name", "model_name"),
                ("revision", "model_revision"),
                ("adapter_version", "adapter_version"),
            )
        )
        or not isinstance(model.get("fingerprint"), str)
        or not re.fullmatch(r"[a-f0-9]{64}", model["fingerprint"])
        or not isinstance(views, list)
        or len(views) != 2
    ):
        raise ValueError("Unproved complete recovery model or limits")
    outputs, count = [], 0
    from .source_inventory import _MAX_ROWS

    for view, dpi in zip(views, (400, 600), strict=True):
        if (
            not isinstance(view, dict)
            or set(view) != {"dpi", "primary", "frame", "selected", "requests"}
            or type(view["dpi"]) is not int
            or view["dpi"] != dpi
        ):
            raise ValueError("Malformed complete recovery view")
        selected, primary = view["selected"], view["primary"]
        if (
            not isinstance(selected, dict)
            or not isinstance(primary, dict)
            or "auxiliary_text" in selected
            or "auxiliary_text_version" in selected
            or selected.get("source_frame") != view["frame"]
        ):
            raise ValueError("Nested or missing complete recovery source")
        if not valid_text_reading(
            selected,
            selected.get("bbox", []),
            dpi,
            maximum_rows=maximum,
            allow_chunks=allow,
        ) or not compatible_primary(primary, selected, view["frame"], dpi, maximum):
            raise ValueError("Recovery changed qualified original text or scope")
        requests = view["requests"]
        if not isinstance(requests, list) or not requests or len(requests) > _MAX_ROWS:
            raise ValueError("Missing or unbounded recovery row inventory")
        grouped = packet["version"] == 3
        selected_requests = [
            (checked_group if grouped else checked_row)(observed, model["fingerprint"])
            for observed in requests
        ]
        selected_parts = parts(selected)
        if len(selected_requests) != len(selected_parts) or any(
            literal(observed["text"]) != literal(part["text"])
            or observed["confidence"] != part["confidence"]
            for observed, part in zip(selected_requests, selected_parts, strict=True)
        ):
            raise ValueError(
                "Recovery outputs do not conserve their original row observations"
            )
        count += (
            sum(len(row["observations"]) for row in requests)
            if grouped
            else len(requests)
        )
        outputs.append(selected)
    if count > _MAX_ROWS or views[0]["primary"]["bbox"] != views[1]["primary"]["bbox"]:
        raise ValueError("Recovery views exceed or disagree on original scope")
    first, second = (parts(selected) for selected in outputs)
    if len(first) != len(second) or any(
        literal(a["text"]) != literal(b["text"])
        for a, b in zip(first, second, strict=True)
    ):
        raise ValueError("Complete recovered source views disagree")
    if all(
        valid_text_reading(
            view["primary"],
            view["primary"]["bbox"],
            dpi,
            maximum_rows=maximum,
            allow_chunks=allow,
        )
        for view, dpi in zip(views, (400, 600), strict=True)
    ):
        raise ValueError("Complete qualified primary source cannot be replaced")
    return tuple(
        {
            **selected,
            **_source_marker(selected),
            "detector_conflict": False,
            "auxiliary_text_version": packet["version"],
            "auxiliary_text": packet,
        }
        for selected in outputs
    )


def _source_marker(selected):
    # Keep the existing auxiliary physical marker even if both outer packet
    # fields are stripped. The inner captured selection stays ordinary and is
    # independently reconstructed against the original pixels on readback.
    name = (
        "physical_text_chunks"
        if "physical_text_chunks" in selected
        else "physical_header_lines"
    )
    return {name: {**selected.get(name, {}), "version": AUXILIARY_TEXT_CELL_VERSION}}


def replay_recovery_cell(reading, page):
    from patent_sar_extractor.core.table_cells import cell_image

    packet = reading["auxiliary_text"]
    for view in packet["views"]:
        dpi, primary = view["dpi"], view["primary"]
        image = cell_image(page, primary["bbox"], dpi)
        if view["frame"] != {
            "dpi": dpi,
            "shape": list(image.shape),
            "pixel_sha256": hashlib.sha256(image.tobytes()).hexdigest(),
        }:
            return False
        engine = RecoveryRowEngine(
            requests=view["requests"],
            fingerprint=packet["model"]["fingerprint"],
            version=packet["version"],
        )
        observed = {
            **source_metadata(primary),
            **observe_text_cell(
                image, dpi, engine, rows_per_chunk=packet["rows_per_chunk"]
            ).evidence(dpi, primary["bbox"]),
        }
        observed["source_frame"] = view["frame"]
        if not engine.complete() or observed != view["selected"]:
            return False
    return True
