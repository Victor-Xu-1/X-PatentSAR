"""Read-only title/context replay and reuse, with no model acquisition."""

from .native_window_coverage import observe_native_window
from .source_geometry import SourceTokens, source_layout
from .source_observations import source_cell_observation
from .source_paint_visibility import native_paint_view, visible_native_tokens
from .title_context_source import (
    TITLE_CONTEXT,
    replay_title_context,
    valid_title_context,
)
from .title_source_proof import (
    MAX_TITLE_SOURCES,
    TITLE_SOURCES,
    raw_title_packet,
    source_title_id,
    source_title_text,
    title_nomination_bounds,
)


def replay_source_title(page, proof, *, layout=None, paint_view=None):
    """Read actual source facts and pixels without repeating title OCR."""
    import hashlib

    from .cell_frame_proof import valid_cell_frame
    from .cell_raster import original_reading_image
    from .heading_title_scope import replay_title_scope
    from .title_source_proof import source_title_geometry

    geometry = source_title_geometry(proof)
    if (
        geometry is None
        or proof["page_no"] != page.number + 1
        or proof["page_size"] != [page.rect.width, page.rect.height]
    ):
        raise ValueError("Original title source geometry is unavailable")
    layout = source_layout(page) if layout is None else layout
    nomination = proof["nomination_source"]
    if proof["ink_source"] is not None:
        from .title_ink_source import replay_title_ink

        replay_title_ink(
            page, proof["ink_source"]["inventory"], layout=layout, paint_view=paint_view
        )
    else:
        proxy = {
            "nomination": {"bbox": title_nomination_bounds(nomination)},
            "page_size": proof["page_size"],
            "title_scope": proof["title_scope"],
        }
        if not replay_title_scope(page, proxy, layout, paint_view=paint_view):
            raise ValueError("Original complete title scope differs")
    actual = source_cell_observation(
        SourceTokens(layout.native, layout), proof["bbox"], native=True
    )
    if (
        actual != proof["native_source"]
        or observe_native_window(page, proof["bbox"], paint_view=paint_view)
        != proof["native_window"]
        or proof["raster_bounds"]
        != (list(layout.raster_bounds) if layout.raster_bounds else None)
    ):
        raise ValueError("Original title native/paint source differs")
    if nomination["origin"] == "native" and nomination != source_cell_observation(
        SourceTokens(layout.native, layout), nomination["bbox"], native=True
    ):
        raise ValueError("Original native title nomination differs")
    if (
        source_title_text(proof) is not None
        and actual["text"].strip()
        and not visible_native_tokens(page, actual, paint_view=paint_view)
    ):
        raise ValueError("Original native title is hidden or covered")
    readings, frames = proof["observations"], proof["rendered_frames"]
    if (
        not isinstance(readings, list)
        or len(readings) not in {0, 2}
        or not isinstance(frames, list)
        or len(frames) != len(readings)
    ):
        raise ValueError("Original title read inventory is incomplete")
    for reading, frame, dpi in zip(
        readings, frames, (400, 600)[: len(readings)], strict=True
    ):
        if (
            not valid_cell_frame(frame, reading, proof["bbox"], dpi)
            or "source_window" not in reading
        ):
            raise ValueError("Original title frame is missing")
        image = original_reading_image(page, proof["bbox"], dpi, reading)
        if frame != {
            "dpi": dpi,
            "shape": list(image.shape),
            "pixel_sha256": hashlib.sha256(image.tobytes()).hexdigest(),
        }:
            raise ValueError("Original title pixels differ")
    if proof.get("auxiliary_title") is not None:
        from .title_lexical_recovery import replay_title_lexical_recovery

        replay_title_lexical_recovery(page, proof)


def reuse_title_sources(page, sources, previous):
    """Recheck current source/pixels, never acquire OCR for an existing title."""
    if not isinstance(previous, list) or len(previous) != len(sources):
        return None
    layout, view, seen, output = source_layout(page), native_paint_view(page), set(), []
    try:
        for current, old in zip(sources, previous, strict=True):
            if raw_title_packet(old) != current or not valid_title_context(
                old, page_no=page.number + 1, width=page.rect.width
            ):
                return None
            replay_title_context(
                page, old[TITLE_CONTEXT], layout=layout, paint_view=view
            )
            records = old.get(TITLE_SOURCES, [])
            if not isinstance(records, list) or len(records) > MAX_TITLE_SOURCES:
                return None
            for record in records:
                key = source_title_id(record)
                if key not in seen:
                    replay_source_title(page, record, layout=layout, paint_view=view)
                    seen.add(key)
            output.append(
                {**current, TITLE_SOURCES: records, TITLE_CONTEXT: old[TITLE_CONTEXT]}
            )
    except (ValueError, TypeError, KeyError, RuntimeError, IndexError, OverflowError):
        return None
    return output
