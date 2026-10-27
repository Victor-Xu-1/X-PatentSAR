"""Mandatory parent native inventory; an omitted title cannot omit its replay."""

import math

from .cell_frame_proof import inside_box
from .source_evidence_identity import proof_id
from .source_geometry import SourceTokens, source_layout
from .source_observations import (
    project_source_observation,
    source_cell_observation,
    source_observation_status,
)
from .title_ink_geometry import title_ink_rows

TITLE_CONTEXT = "title_context"
TITLE_METADATA = {TITLE_CONTEXT, "original_titles"}


def raw_title_parent(packet):
    return {key: value for key, value in packet.items() if key not in TITLE_METADATA}


def original_title_raw_owner(parent, record):
    """The validated complete source owns an ink row beyond a local projection."""
    ink = record.get("ink_source")
    if ink is None:
        return raw_title_parent(parent)
    context = parent.get(TITLE_CONTEXT)
    if not isinstance(context, dict) or ink.get("inventory") != context.get(
        "ink_source"
    ):
        return None
    return context.get("native_source")


def title_context_bounds(context):
    if (
        not isinstance(context, dict)
        or set(context)
        != {
            "version",
            "page_no",
            "page_size",
            "native_source",
            "raster_bounds",
            "ink_source",
        }
        or type(context["version"]) is not int
        or context["version"] != 1
    ):
        return None
    size, native = context["page_size"], context["native_source"]
    if (
        type(context["page_no"]) is not int
        or not 1 <= context["page_no"] <= 20000
        or not isinstance(size, list)
        or len(size) != 2
        or any(
            type(v) not in {int, float} or not math.isfinite(v) or v <= 0 for v in size
        )
        or not isinstance(native, dict)
    ):
        return None
    bounds = native.get("bbox")
    if (
        native.get("origin") != "native"
        or source_observation_status(native, bounds, native.get("text")) == "invalid"
        or not inside_box(bounds, [0, 0, *size])
    ):
        return None
    raster = context["raster_bounds"]
    ink = context["ink_source"]
    if ink is not None and (
        title_ink_rows(ink) is None
        or ink["page_no"] != context["page_no"]
        or ink["page_size"] != size
        or ink["bbox"] != bounds
        or ink["native_source"] != native
    ):
        return None
    return bounds if raster is None or inside_box(raster, [0, 0, *size]) else None


def valid_title_context(parent, *, page_no=None, width=None):
    if (
        not isinstance(parent, dict)
        or source_observation_status(parent, parent.get("bbox"), parent.get("text"))
        == "invalid"
    ):
        return False
    context = parent.get(TITLE_CONTEXT)
    bounds = title_context_bounds(context)
    if (
        bounds is None
        or not inside_box(parent["bbox"], bounds)
        or page_no is not None
        and context["page_no"] != page_no
        or width is not None
        and context["page_size"][0] != width
    ):
        return False
    return parent["origin"] != "native" or raw_title_parent(
        parent
    ) == project_source_observation(context["native_source"], parent["bbox"])


def observe_title_context(page, bounds, layout, paint_view, *, ink_source=None):
    bounds = ink_source["bbox"] if ink_source is not None else bounds
    return {
        "version": 1,
        "page_no": page.number + 1,
        "page_size": [page.rect.width, page.rect.height],
        "native_source": source_cell_observation(
            SourceTokens(layout.native, layout), bounds, native=True
        ),
        "raster_bounds": list(layout.raster_bounds) if layout.raster_bounds else None,
        "ink_source": ink_source,
    }


def replay_title_context(page, context, *, layout=None, paint_view=None):
    bounds = title_context_bounds(context)
    if (
        bounds is None
        or context["page_no"] != page.number + 1
        or context["page_size"] != [page.rect.width, page.rect.height]
    ):
        raise ValueError("Original title context geometry differs")
    layout = source_layout(page) if layout is None else layout
    ink = context["ink_source"]
    if ink is not None:
        from .title_ink_source import replay_title_ink

        replay_title_ink(page, ink, layout=layout, paint_view=paint_view)
    if context != observe_title_context(
        page, bounds, layout, paint_view, ink_source=ink
    ):
        raise ValueError("Original title context native inventory differs")


def title_context_id(context):
    return proof_id({"status": "observed_original_title_context", "source": context})
