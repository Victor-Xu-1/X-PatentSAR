"""Actual native/pixel replay for the sole explicit role-text source inventory."""

from .activity_grid_roles import MAX_ROLE_ROW_HEIGHT, MAX_ROLE_TEXT_ROWS
from .cell_frame_proof import inside_box, original_cell_frame_matches
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
from .text_ocr.cell_proof import has_auxiliary_text


def original_role_source_errors(document, sources):
    """Auxiliary packets are checked by the existing shared auxiliary replayer.

    Ordinary optical sources use its existing frame/pixel/chunk authority.
    Native sources reread actual original native words and independent raster
    ownership once per page. No OCR/model, saved path or role inference occurs.
    """
    layouts = {}
    try:
        for page_no, cell in sources:
            if not isinstance(cell, dict):
                return ["Malformed original role-text source."]
            if has_auxiliary_text(cell):
                continue
            if type(page_no) is not int or not 1 <= page_no <= len(document):
                return ["Original role-text page ownership is unavailable."]
            page = document[page_no - 1]
            bounds = cell.get("bbox")
            if not inside_box(bounds, [0, 0, page.rect.width, page.rect.height]):
                return ["Original role-text cell leaves its original page."]
            method = cell.get("method")
            if method == "native_cell":
                if page_no not in layouts:
                    layouts[page_no] = source_layout(page)
                layout = layouts[page_no]
                tokens = SourceTokens(layout.native, layout, layout.raster_bounds)
                text = cell.get("text")
                profile = source_cell_observation(tokens, bounds, native=True)
                if (
                    not isinstance(text, str)
                    or len(text) > 4096
                    or native_cell_text(tokens, bounds) != text
                    or text.strip()
                    and not native_region(tokens, bounds, False)
                    or layout.raster_bounds is not None
                    and overlaps(layout.raster_bounds, bounds)
                    or cell.get("source_observation") != profile
                    or bool(text and text.strip())
                    and not visible_native_tokens(page, profile)
                    or not bool(text and text.strip())
                    and not original_grid_cell_is_empty(page, bounds)
                ):
                    return ["Native role text differs from its actual original source."]
            elif method in ("cell_ocr_400dpi", "cell_ocr_600dpi"):
                if not original_cell_frame_matches(
                    cell,
                    page,
                    maximum_row_height=MAX_ROLE_ROW_HEIGHT,
                    maximum_rows=MAX_ROLE_TEXT_ROWS,
                ):
                    return ["Original role text differs from its original page pixels."]
            else:
                return ["Original role-text source method is unavailable."]
    except (
        OSError,
        TypeError,
        ValueError,
        KeyError,
        IndexError,
        RuntimeError,
        OverflowError,
    ):
        return ["Original role-text replay is unavailable."]
    return []
