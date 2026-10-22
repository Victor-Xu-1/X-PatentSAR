"""Original raster pixel axes in rendered PDF points, not nominal output DPI."""

import math

import fitz

from .reaction_arrows import contained
from .reaction_vectors import valid_rectangle
from .source_geometry import overlaps

MAX_RASTER_SOURCES = 4096


def pixel_source_required(sources, regions):
    return any(
        not any(contained(image["bbox"], region) for region in regions)
        for image in sources
    )


def validate_raster_layout(sources, size, bounds):
    if not isinstance(sources, list) or len(sources) > MAX_RASTER_SOURCES:
        raise ValueError("Original raster layout bound exceeded")
    for item in sources:
        if not isinstance(item, dict) or set(item) != {"bbox", "pixel_axes"}:
            raise ValueError("Malformed original raster geometry")
        axes = item["pixel_axes"]
        if (
            not valid_rectangle(item["bbox"], size)
            or not overlaps(item["bbox"], bounds)
            or not isinstance(axes, list)
            or len(axes) != 2
            or any(not isinstance(axis, list) or len(axis) != 2 for axis in axes)
            or any(
                type(v) not in {int, float} or not math.isfinite(v) or abs(v) > 100000
                for axis in axes
                for v in axis
            )
            or any(math.hypot(*axis) <= 0 for axis in axes)
        ):
            raise ValueError("Invalid original raster pixel axes")


def observe_raster_layout(page, bounds):
    images = page.get_image_info()
    if len(images) > MAX_RASTER_SOURCES:
        raise ValueError("Original raster layout bound exceeded")
    sources, rotation = [], page.rotation_matrix
    for image in images:
        rectangle = (fitz.Rect(image["bbox"]) * rotation) & page.rect
        if rectangle.is_empty or not overlaps(list(rectangle), bounds):
            continue
        width, height = image["width"], image["height"]
        if type(width) is not int or type(height) is not int or min(width, height) <= 0:
            raise ValueError("Invalid original raster dimensions")
        matrix = fitz.Matrix(image["transform"])
        axes = [
            [matrix.a / width, matrix.b / width],
            [matrix.c / height, matrix.d / height],
        ]
        sources.append(
            {
                "bbox": list(rectangle),
                "pixel_axes": [
                    [x * rotation.a + y * rotation.c, x * rotation.b + y * rotation.d]
                    for x, y in axes
                ],
            }
        )
    validate_raster_layout(sources, [page.rect.width, page.rect.height], bounds)
    return sources


def _original_pixel_step(sources, bounds):
    """Axis-aligned support of the actual image pixel parallelogram."""
    return max(
        [
            0.0,
            *(
                max(abs(a[0]) + abs(b[0]), abs(a[1]) + abs(b[1]))
                for item in sources
                if overlaps(item["bbox"], bounds)
                for a, b in [item["pixel_axes"]]
            ),
        ]
    )


def source_pixel_step(sources, bounds, dpi):
    # Rendering a100-dpi scan at600dpi does not create600-dpi information.
    return max(72 / dpi, _original_pixel_step(sources, bounds))


def render_pixel_support(sources, bounds, dpi):
    """Source texel and output pixel supports compose; information does not."""
    return 72 / dpi + _original_pixel_step(sources, bounds)
