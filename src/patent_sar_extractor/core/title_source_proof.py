"""Pure complete original-title proof, independent of catalogue role semantics."""

import math

from .cell_frame_proof import inside_box, valid_cell_frame
from .cell_text_proof import valid_text_reading
from .heading_source_geometry import (
    MAX_HEADING_HEIGHT,
    MAX_HEADING_ROWS,
    heading_bounds,
)
from .heading_title_geometry import title_scope_bounds
from .native_title_claims import native_title_agrees, title_literal
from .native_window_coverage import native_window_complete, valid_native_window
from .source_cell_pixels import cell_readings_conserve_ink, closed_cell_masks
from .source_evidence_identity import proof_id
from .source_geometry import overlaps
from .source_observations import source_observation_status
from .title_context_source import TITLE_METADATA, raw_title_parent, valid_title_context
from .title_ink_geometry import title_ink_rows

TITLE_SOURCES = "original_titles"
MAX_TITLE_SOURCES = 128


def source_title_id(proof):
    return proof_id({"status": "observed_original_title", "source": proof})


def raw_title_packet(packet):
    return raw_title_parent(packet)


def title_nomination_bounds(packet):
    tokens = packet.get("tokens", [])
    return (
        [
            min(t["bbox"][0] for t in tokens),
            min(t["bbox"][1] for t in tokens),
            max(t["bbox"][2] for t in tokens),
            max(t["bbox"][3] for t in tokens),
        ]
        if tokens
        else None
    )


def source_title_geometry(proof):
    if (
        not isinstance(proof, dict)
        or set(proof)
        != {
            "version",
            "page_no",
            "page_size",
            "nomination_source",
            "bbox",
            "native_source",
            "native_window",
            "raster_bounds",
            "title_scope",
            "ink_source",
            "observations",
            "rendered_frames",
        }
        or type(proof["version"]) is not int
        or proof["version"] != 1
    ):
        return None
    size, nomination = proof["page_size"], proof["nomination_source"]
    if (
        type(proof["page_no"]) is not int
        or not 1 <= proof["page_no"] <= 20000
        or not isinstance(size, list)
        or len(size) != 2
        or any(
            type(value) not in {int, float} or not math.isfinite(value) or value <= 0
            for value in size
        )
        or not isinstance(nomination, dict)
    ):
        return None
    if (
        source_observation_status(
            nomination, nomination.get("bbox"), nomination.get("text")
        )
        == "invalid"
        or TITLE_METADATA.intersection(nomination)
        or not inside_box(nomination["bbox"], [0, 0, *size])
    ):
        return None
    nominated = title_nomination_bounds(nomination)
    ink = proof["ink_source"]
    if ink is not None:
        if not isinstance(ink, dict) or set(ink) != {"inventory", "row_index"}:
            return None
        inventory, index = ink["inventory"], ink["row_index"]
        rows = title_ink_rows(inventory)
        if (
            rows is None
            or rows[1] is not None
            or type(index) is not int
            or not 0 <= index < len(rows[0])
            or not rows[0][index]["requires_read"]
            or proof["page_no"] != inventory["page_no"]
            or size != inventory["page_size"]
            or proof["title_scope"] is not None
        ):
            return None
        from .source_observations import project_source_observation

        bounds = rows[0][index]["bbox"]
        if proof["bbox"] != bounds or nomination != project_source_observation(
            inventory["native_source"], bounds
        ):
            return None
        return bounds, None
    if nominated is None:
        return None
    scope = proof["title_scope"]
    if scope is not None:
        scoped = title_scope_bounds(scope, nominated, size)
        if scoped is None:
            return None
        expected, refusal = scoped
    else:
        row = heading_bounds(nominated, size)
        expected = [0, row.y0, size[0], row.y1]
        refusal = None
    return (
        (expected, refusal)
        if expected == proof["bbox"]
        and inside_box(expected, [0, 0, *size])
        and expected[3] - expected[1] <= MAX_HEADING_HEIGHT
        else None
    )


def source_title_text(proof):
    geometry = source_title_geometry(proof)
    if (
        geometry is None
        or geometry[1] is not None
        or proof["nomination_source"].get("boundary_tokens")
        or proof["ink_source"] is None
        and proof["nomination_source"]["origin"] == "native"
        and source_observation_status(
            proof["nomination_source"],
            proof["nomination_source"]["bbox"],
            proof["nomination_source"]["text"],
        )
        != "qualified"
    ):
        return None
    bounds = geometry[0]
    native, window = proof["native_source"], proof["native_window"]
    if (
        not isinstance(native, dict)
        or native.get("origin") != "native"
        or source_observation_status(native, bounds, native.get("text")) == "invalid"
        or not valid_native_window(window, bounds)
        or window["page_size"] != proof["page_size"]
    ):
        return None
    if (
        (native["tokens"] or native.get("boundary_tokens"))
        and proof["title_scope"] is None
        and proof["ink_source"] is None
    ):
        return None
    raster = proof["raster_bounds"]
    if raster is not None and not inside_box(raster, [0, 0, *proof["page_size"]]):
        return None
    observations, frames = proof["observations"], proof["rendered_frames"]
    if (
        not isinstance(observations, list)
        or not isinstance(frames, list)
        or len(observations) not in {0, 2}
        or len(frames) != len(observations)
    ):
        return None
    if not observations:
        return (
            native["text"]
            if native_window_complete(window, native)
            and not (raster is not None and overlaps(raster, bounds))
            else None
        )
    scope = proof["title_scope"]
    if scope is not None and scope["method"] == "closed_cell":
        masks = closed_cell_masks(
            scope["cell_source"]["pixels"], bounds, proof["page_size"]
        )
        if masks is None or not cell_readings_conserve_ink(masks, observations):
            return None
    for reading, frame, dpi in zip(observations, frames, (400, 600), strict=True):
        if not valid_text_reading(
            reading,
            bounds,
            dpi,
            maximum_row_height=MAX_HEADING_HEIGHT,
            maximum_rows=MAX_HEADING_ROWS,
        ) or not valid_cell_frame(frame, reading, bounds, dpi):
            return None
    texts = [reading["raw_text"] for reading in observations]
    if title_literal(texts[0]) != title_literal(texts[1]) or not native_title_agrees(
        proof, texts[0]
    ):
        return None
    nomination = proof["nomination_source"]
    if (
        nomination["origin"] == "raster"
        and source_observation_status(
            nomination, nomination["bbox"], nomination["text"]
        )
        == "qualified"
    ):
        from .caption_role_semantics import catalog_title_role
        from .source_table_roles import title_key

        old_role, new_role = (
            catalog_title_role(nomination["text"]),
            catalog_title_role(texts[0]),
        )
        old_key = title_key(nomination["text"])
        if (old_role != "unknown" and old_role != new_role) or (
            old_key and old_key != title_key(texts[0])
        ):
            return None
    return texts[0]


def title_packet_text(packet):
    """Raw words nominate a title; only its matching complete source supplies text."""
    if not valid_title_context(packet):
        return None
    records = packet.get(TITLE_SOURCES)
    if not isinstance(records, list) or not 1 <= len(records) <= MAX_TITLE_SOURCES:
        return None
    raw = raw_title_packet(packet)
    matches = [
        record
        for record in records
        if isinstance(record, dict) and record.get("nomination_source") == raw
    ]
    return source_title_text(matches[0]) if len(matches) == 1 else None
