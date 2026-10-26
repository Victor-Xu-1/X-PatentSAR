"""Complete title observation through existing scope, paint and text-cell SDKs."""

from . import page_ocr_cache
from .cell_frame_proof import inside_box
from .cell_raster import cell_pixel_rect
from .heading_source_geometry import (
    MAX_HEADING_HEIGHT,
    MAX_HEADING_ROWS,
    heading_bounds,
)
from .heading_title_geometry import title_scope_bounds
from .heading_title_scope import observe_title_scope
from .native_window_coverage import observe_native_window
from .paired_text_observation import observe_paired_text
from .source_evidence_identity import proof_id
from .source_geometry import SourceTokens, source_layout
from .source_observations import (
    project_source_observation,
    source_cell_observation,
    source_observation_status,
)
from .source_paint_visibility import native_paint_view, visible_native_tokens
from .title_context_source import (
    TITLE_CONTEXT,
    observe_title_context,
)
from .title_ink_geometry import title_ink_rows
from .title_ink_source import observe_title_ink
from .title_source_proof import (
    MAX_TITLE_SOURCES,
    TITLE_SOURCES,
    raw_title_packet,
    source_title_text,
    title_nomination_bounds,
)


def observe_source_title(page, nomination, *, layout, paint_view, ink_source=None):
    raw = raw_title_packet(nomination)
    size = [page.rect.width, page.rect.height]
    nominated = title_nomination_bounds(raw)
    if nominated is None and ink_source is None:
        raise ValueError("Original title has no retained word nomination")
    scope, scoped = None, None
    if ink_source is not None:
        rows = title_ink_rows(ink_source["inventory"])
        if rows is None or rows[1] is not None:
            raise ValueError("Unproved original title-ink rows")
        bounds = rows[0][ink_source["row_index"]]["bbox"]
    else:
        scope = observe_title_scope(page, nominated, layout, paint_view=paint_view)
        scoped = (
            title_scope_bounds(scope, nominated, size) if scope is not None else None
        )
        row = heading_bounds(nominated, size)
        bounds = scoped[0] if scoped is not None else [0, row.y0, size[0], row.y1]
    native = source_cell_observation(
        SourceTokens(layout.native, layout), bounds, native=True
    )
    proof = {
        "version": 1,
        "page_no": page.number + 1,
        "page_size": size,
        "nomination_source": raw,
        "bbox": list(bounds),
        "native_source": native,
        "native_window": observe_native_window(page, bounds, paint_view=paint_view),
        "raster_bounds": list(layout.raster_bounds) if layout.raster_bounds else None,
        "title_scope": scope,
        "ink_source": ink_source,
        "observations": [],
        "rendered_frames": [],
    }
    if (
        raw.get("boundary_tokens")
        or ink_source is None
        and raw["origin"] == "native"
        and source_observation_status(raw, raw["bbox"], raw["text"]) != "qualified"
        or bounds[3] - bounds[1] > MAX_HEADING_HEIGHT
        or scope is not None
        and (scoped is None or scoped[1] is not None)
    ):
        return proof
    if native["text"].strip() and (
        source_observation_status(native, bounds, native["text"]) != "qualified"
        or not visible_native_tokens(page, native, paint_view=paint_view)
    ):
        return proof
    if (
        scope is None
        and ink_source is None
        and (native["tokens"] or native.get("boundary_tokens"))
    ):
        return proof
    if source_title_text(proof) is not None:
        return proof
    if any(
        cell_pixel_rect(bounds, dpi).width * cell_pixel_rect(bounds, dpi).height
        > 8_000_000
        for dpi in (400, 600)
    ):
        return proof
    engine = page_ocr_cache.get_ocr_engine()
    if not engine or engine[0] != "rapidocr":
        return proof
    proof["observations"], proof["rendered_frames"] = observe_paired_text(
        page,
        bounds,
        engine[1],
        lambda raw, _kind: raw,
        maximum_rows=MAX_HEADING_ROWS,
        maximum_row_height=MAX_HEADING_HEIGHT,
    )
    if source_title_text(proof) is None:
        from .text_ocr.source_capture import refine_source_text

        proof["observations"] = refine_source_text(
            page,
            bounds,
            proof["observations"],
            maximum_rows=MAX_HEADING_ROWS,
            maximum_row_height=MAX_HEADING_HEIGHT,
        )
    return proof


def attach_title_sources(page, sources, nominations, *, context=None):
    """Attach exact nominated witnesses to existing raw parent carriers only."""
    if (
        not isinstance(sources, list)
        or len(sources) > MAX_TITLE_SOURCES
        or any(
            not isinstance(source, dict)
            or source_observation_status(source, source.get("bbox"), source.get("text"))
            == "invalid"
            for source in sources
        )
    ):
        raise ValueError("Malformed original title parent inventory")
    if not isinstance(nominations, list) or len(nominations) > MAX_TITLE_SOURCES:
        raise ValueError("Original title inventory exceeds its bound")
    if not sources:
        if nominations or context is not None:
            raise ValueError("Original titles have no context owner")
        return []
    if context is not None and len(sources) > 2:
        raise ValueError("Original title context has competing source parents")
    layout, view = source_layout(page), native_paint_view(page)
    unique = {proof_id(raw_title_packet(p)): raw_title_packet(p) for p in nominations}
    records = [
        observe_source_title(page, p, layout=layout, paint_view=view)
        for p in unique.values()
    ]
    ink = None
    if not nominations and context is not None:
        ink = observe_title_ink(
            page,
            sources[0]["bbox"],
            context,
            layout=layout,
            paint_view=view,
        )
        rows = title_ink_rows(ink)
        if rows is not None and rows[1] is None:
            records.extend(
                observe_source_title(
                    page,
                    project_source_observation(ink["native_source"], row["bbox"]),
                    layout=layout,
                    paint_view=view,
                    ink_source={"inventory": ink, "row_index": index},
                )
                for index, row in enumerate(rows[0])
                if row["requires_read"]
            )
    output = []
    for source in sources:
        selected = []
        for record in records:
            raw = record["nomination_source"]
            if (
                source["origin"] == raw["origin"]
                and inside_box(raw["bbox"], source["bbox"])
                and raw_title_packet(project_source_observation(source, raw["bbox"]))
                == raw
            ):
                selected.append(record)
        output.append(
            {
                **source,
                TITLE_SOURCES: selected,
                TITLE_CONTEXT: observe_title_context(
                    page, source["bbox"], layout, view, ink_source=ink
                ),
            }
        )
    return output
