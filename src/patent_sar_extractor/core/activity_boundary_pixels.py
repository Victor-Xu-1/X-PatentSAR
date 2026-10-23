"""Geometry-only adapter to the shared full-original cell raster SDK."""

from .cell_frame_proof import valid_cell_frame
from .cell_raster import render_cell_raster


def capture_boundary_pixels(page, bounds):
    raster = render_cell_raster(page, bounds, 400, purpose="pixels")
    return {"frame": raster.frame, "window": raster.source_window}


def valid_boundary_pixels(pixels, bounds):
    if not isinstance(pixels, dict) or set(pixels) != {"frame", "window"}:
        return False
    window = pixels["window"]
    # This is only a full pixel owner. It makes no OCR/empty-text claim, removes
    # no frame/ink and uses the same bounded frame validator as ordinary cells.
    return (
        isinstance(window, dict)
        and window.get("purpose") == "pixels"
        and valid_cell_frame(
            pixels["frame"],
            {
                "source_window": window,
                "raw_text": "",
                "text": "",
                "parts": [],
                "detection_parts": [],
                "border_pixels": 0,
            },
            bounds,
            400,
        )
    )


def original_boundary_pixels_match(scope, bounds, page):
    if scope["page_size"] != [page.rect.width, page.rect.height]:
        return False
    pixels = scope["original_pixels"]
    if scope["prefix"]["origin"] == "native":
        return pixels is None  # Whole native paint/visibility replay is separate.
    return valid_boundary_pixels(pixels, bounds) and pixels == capture_boundary_pixels(
        page, bounds
    )
