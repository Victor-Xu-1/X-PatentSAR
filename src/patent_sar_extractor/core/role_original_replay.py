"""Actual native/pixel replay for the sole explicit role-text source inventory."""

from .activity_grid_roles import MAX_ROLE_ROW_HEIGHT, MAX_ROLE_TEXT_ROWS
from .cell_frame_proof import inside_box, original_cell_frame_matches
from .native_cell_replay import original_native_cell_matches
from .source_geometry import source_layout
from .source_paint_visibility import native_paint_view
from .text_ocr.cell_proof import has_auxiliary_text
from .title_geometry_memo import title_geometry_call


@title_geometry_call
def original_role_source_errors(document, sources):
    """Auxiliary packets are checked by the existing shared auxiliary replayer.

    Ordinary optical sources use its existing frame/pixel/chunk authority.
    Native sources reread actual original native words and independent raster
    ownership once per page. No OCR/model, saved path or role inference occurs.
    """
    layouts, paints = {}, {}
    try:
        for page_no, cell in sources:
            if not isinstance(cell, dict):
                return ["Malformed original role-text source."]
            if has_auxiliary_text(cell):
                continue
            if type(page_no) is not int or not 1 <= page_no <= len(document):
                return ["Original role-text page ownership is unavailable."]
            page = document[page_no - 1]
            if cell.get("method") == "original_title_context":
                if set(cell) != {"method", "title_context"}:
                    return ["Malformed original title context carrier."]
                from .title_context_source import replay_title_context

                if page_no not in layouts:
                    layouts[page_no] = source_layout(page)
                    paints[page_no] = native_paint_view(page)
                replay_title_context(
                    page,
                    cell["title_context"],
                    layout=layouts[page_no],
                    paint_view=paints[page_no],
                )
                continue
            if cell.get("method") == "original_title":
                if set(cell) != {"method", "title_source"}:
                    return ["Malformed original title source carrier."]
                from .title_original_replay import replay_source_title

                if page_no not in layouts:
                    layouts[page_no] = source_layout(page)
                    paints[page_no] = native_paint_view(page)
                replay_source_title(
                    page,
                    cell["title_source"],
                    layout=layouts[page_no],
                    paint_view=paints[page_no],
                )
                continue
            bounds = cell.get("bbox")
            if not inside_box(bounds, [0, 0, page.rect.width, page.rect.height]):
                return ["Original role-text cell leaves its original page."]
            method = cell.get("method")
            if method == "native_cell":
                if page_no not in layouts:
                    layouts[page_no] = source_layout(page)
                    paints[page_no] = native_paint_view(page)
                if not original_native_cell_matches(
                    page, cell, layout=layouts[page_no], paint_view=paints[page_no]
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
