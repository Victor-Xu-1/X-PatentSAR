"""Source-owned auxiliary title views; original high-score reads stay immutable."""

from .heading_source_geometry import MAX_HEADING_HEIGHT, MAX_HEADING_ROWS
from .text_ocr.recovery_proof import recovery_observation_views
from .title_lexical_policy import eligible_title_literal, title_tokens


def recovered_title_observation(proof):
    """A separate title witness cannot be reused as a generic measurement cell."""
    try:
        expected = eligible_title_literal(proof)
        packet = proof["auxiliary_title"]
        if (
            expected is None
            or not isinstance(packet, dict)
            or packet.get("rows_per_chunk") != MAX_HEADING_ROWS
            or packet.get("maximum_row_height") != MAX_HEADING_HEIGHT
            or packet.get("allow_chunks") is not False
        ):
            return None
        selected = recovery_observation_views(packet)
        if any(
            view["primary"] != primary
            or view["frame"] != frame
            or len(reading.get("parts", [])) != 1
            or title_tokens(reading["raw_text"]) != title_tokens(expected)
            for view, primary, frame, reading in zip(
                packet["views"],
                proof["observations"],
                proof["rendered_frames"],
                selected,
                strict=True,
            )
        ):
            return None
        # Return the independently observed text, never a guessed/spliced word.
        return selected[0]["raw_text"], False
    except (KeyError, TypeError, ValueError, IndexError, AttributeError, OverflowError):
        return None


def capture_title_lexical_recovery(page, proof):
    if eligible_title_literal(proof) is None:
        return
    from .text_ocr.configuration import get_auxiliary_text_runtime

    auxiliary = get_auxiliary_text_runtime()
    if auxiliary is None:
        return
    from .cell_raster import original_reading_image
    from .text_ocr.recovery_capture import capture_complete_views

    images = tuple(
        original_reading_image(page, proof["bbox"], dpi, primary)
        for primary, dpi in zip(proof["observations"], (400, 600), strict=True)
    )
    attempts = []
    packet = capture_complete_views(
        images,
        proof["observations"],
        auxiliary,
        maximum_rows=MAX_HEADING_ROWS,
        maximum_row_height=MAX_HEADING_HEIGHT,
        allow_chunks=False,
        evidence_sink=attempts,
    )
    if packet is not None:
        if (
            recovered_title_observation({**proof, "auxiliary_title": packet})
            is not None
        ):
            proof["auxiliary_title"] = packet
        else:
            attempts.append(
                {
                    "status": "rejected",
                    "code": "title_claims_disagree",
                    "packet": packet,
                }
            )
    proof["auxiliary_title_attempts"].extend(attempts)


def replay_title_lexical_recovery(page, proof):
    if recovered_title_observation(proof) is None:
        raise ValueError("Auxiliary title claims are unavailable or conflicting")
    from .text_ocr.recovery_proof import replay_recovery_cell

    if not replay_recovery_cell({"auxiliary_text": proof["auxiliary_title"]}, page):
        raise ValueError("Auxiliary title rows differ from their original pixels")
