"""Original native-cell identity and visibility, without OCR or role inference."""

from .cell_frame_proof import inside_box
from .source_cell_claims import cell_source_status, native_witness
from .source_cell_pixels import original_grid_cell_is_empty
from .source_geometry import (
    SourceTokens,
    native_cell_text,
    native_region,
    overlaps,
    source_layout,
)
from .source_observations import source_cell_observation
from .source_paint_visibility import visible_native_tokens


def original_native_cell_matches(page, cell, *, layout=None, paint_view=None):
    """A saved profile must equal visible text from the caller's actual source.

    The optional layout is call-local original-page work, not a saved packet.
    No model, path from an artifact, semantic interpretation or status flag
    supplies admission. A text-empty cell still needs actual closed-grid pixels.
    """
    if not isinstance(cell, dict) or cell.get("method") != "native_cell":
        return False
    bounds, text = cell.get("bbox"), cell.get("text")
    if (
        not inside_box(bounds, [0, 0, page.rect.width, page.rect.height])
        or not isinstance(text, str)
        or len(text) > 4096
        or cell_source_status(cell) == "invalid"
    ):
        return False
    if layout is None:
        layout = source_layout(page)
    tokens = SourceTokens(layout.native, layout, layout.raster_bounds)
    profile = source_cell_observation(tokens, bounds, native=True)
    if (
        native_cell_text(tokens, bounds) != text
        or cell.get("source_observation") != profile
    ):
        return False
    if native_witness(cell):
        # This proves the retained native layer only. Pixel observations and
        # unchanged literal-conflict gates must independently prove the value.
        # A shadow may coexist with a raster source or be non-visible; it never
        # establishes a printed value, identifier, metadata count or blank.
        return True
    if (
        text.strip()
        and not native_region(tokens, bounds, False)
        or layout.raster_bounds is not None
        and overlaps(layout.raster_bounds, bounds)
    ):
        return False
    return (
        visible_native_tokens(page, profile, paint_view=paint_view)
        if text.strip()
        else original_grid_cell_is_empty(page, bounds)
    )
