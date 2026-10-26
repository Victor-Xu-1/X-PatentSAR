"""One integer raster-extent authority for original text-row admission/replay."""

PHYSICAL_ROW_GAP = 0.7


def row_pixel_limit(dpi, *, maximum_row_height=12):
    """Cover the point interval and its unknown subpixel render-origin phase.

    A 12pt interval spans 66.67 pixels at400dpi. A partially covered pixel at
    either end can make its raster envelope68 pixels (101 at600dpi). This is
    one fixed integer coverage bound, not a data-dependent tolerance or retry.
    """
    if (
        type(dpi) is not int
        or dpi not in {400, 600}
        or type(maximum_row_height) is not int
        or not 0 < maximum_row_height <= 128
    ):
        raise ValueError("Invalid original text-row extent")
    return (maximum_row_height * dpi + 71) // 72 + 1
