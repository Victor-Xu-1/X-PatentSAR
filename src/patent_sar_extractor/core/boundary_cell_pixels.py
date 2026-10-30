"""Paired four-edge closure for cells wholly outside a touching title window.

These strips are ONLY a rule-contact witness. Unobserved cell interiors cannot
qualify text, body ink or blankness; the ordinary full-cell SDK remains required.
"""

import numpy as np

from .cell_frame_proof import inside_box
from .cell_raster import cell_pixel_rect
from .plot_reference_pixels import observe_pixels, retained_pixels

KIND = "original_cell_boundary"


def boundary_strips(cell, size):
    from .source_cell_pixels import source_window

    window = source_window(cell, size)
    return [
        [window[0], window[1], min(window[2], cell[0] + 3), window[3]],
        [max(window[0], cell[2] - 3), window[1], window[2], window[3]],
        [window[0], window[1], window[2], min(window[3], cell[1] + 3)],
        [window[0], max(window[1], cell[3] - 3), window[2], window[3]],
    ]


def boundary_pixel_cost(cell, size):
    return sum(
        rectangle.width * rectangle.height
        for strip in boundary_strips(cell, size)
        for rectangle in (cell_pixel_rect(strip, 600),)
    )


def boundary_cell_masks(packet, cell, size):
    from .source_cell_pixels import MAX_CELL_PIXELS, _interior, source_window

    if (
        not isinstance(packet, dict)
        or set(packet) != {"kind", "version", "bbox", "cell", "strips"}
        or packet["kind"] != KIND
        or type(packet["version"]) is not int
        or packet["version"] != 1
        or not inside_box(cell, [0, 0, *size])
        or packet["cell"] != list(cell)
        or packet["bbox"] != source_window(cell, size)
        or not isinstance(packet["strips"], list)
        or len(packet["strips"]) != 4
        or boundary_pixel_cost(cell, size) > MAX_CELL_PIXELS
    ):
        return None
    window, strips = packet["bbox"], boundary_strips(cell, size)
    if any(
        not isinstance(source, dict)
        or set(source) != {"bbox", "readings"}
        or source["bbox"] != strip
        or not isinstance(source["readings"], list)
        or len(source["readings"]) != 2
        for source, strip in zip(packet["strips"], strips, strict=True)
    ):
        return None
    masks = []
    for index, dpi in enumerate((400, 600)):
        extent = cell_pixel_rect(window, dpi)
        if extent.width * extent.height > MAX_CELL_PIXELS:
            return None
        # This is an internal edge-projection canvas, NOT original interior
        # pixels or a saved full-cell carrier. Only observed strip bits enter.
        mask = np.zeros((extent.height, extent.width), dtype=bool)
        covered = np.zeros_like(mask)
        for source, strip in zip(packet["strips"], strips, strict=True):
            reading = source["readings"][index]
            bits = retained_pixels(reading, strip, dpi, MAX_CELL_PIXELS)
            part = cell_pixel_rect(strip, dpi)
            if (
                bits is None
                or bits.shape != (part.height, part.width)
                or "source_window" not in reading
                or reading["source_window"]["purpose"] != "pixels"
                or reading["source_window"]["read_bounds"]
                != [0, 0, part.width, part.height]
            ):
                return None
            y, x = part.y0 - extent.y0, part.x0 - extent.x0
            target = mask[y : y + part.height, x : x + part.width]
            overlap = covered[y : y + part.height, x : x + part.width]
            if target.shape != bits.shape:
                return None
            # Clipped raster interpolation can differ at strip corners. Never
            # vote/fill an edge: overlapping observations contribute only their
            # common actually black pixels, with every raw strip still retained.
            target[overlap] &= bits[overlap].astype(bool)
            target[~overlap] = bits[~overlap]
            overlap[:] = True
        edges = _interior(
            mask, cell, window, dpi, {}, boundary_only=True, origin_override=extent
        )
        if edges is None:
            return None
        masks.append(edges)
    return masks


def observe_boundary_cell(page, cell):
    from .source_cell_pixels import MAX_CELL_PIXELS, source_window

    size = [page.rect.width, page.rect.height]
    window = source_window(cell, size)
    extent = cell_pixel_rect(window, 600)
    if (
        not inside_box(cell, [0, 0, *size])
        or extent.width * extent.height > MAX_CELL_PIXELS
        or boundary_pixel_cost(cell, size) > MAX_CELL_PIXELS
    ):
        return None
    strips = [
        observe_pixels(page, bounds, MAX_CELL_PIXELS)
        for bounds in boundary_strips(cell, size)
    ]
    if any(source is None for source in strips):
        return None
    packet = {
        "kind": KIND,
        "version": 1,
        "bbox": window,
        "cell": list(cell),
        "strips": strips,
    }
    return packet if boundary_cell_masks(packet, cell, size) is not None else None
