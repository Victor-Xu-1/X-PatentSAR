"""Bounded image literals in rejected diagnostics, never original-role proof."""


def bounded_large_pixel_packet(packet, *, text_limit):
    """Only a complete existing pixel-SDK carrier owns a large mask scalar.

    Decoding checks geometry, DPI, compression, padding and the current pixel
    bound. It does NOT establish original-source equality, a role or acceptance.
    Ordinary text and arbitrary dictionaries cannot borrow this permission.
    """
    if not isinstance(packet, dict) or set(packet) != {"bbox", "readings"}:
        return False
    readings, bounds = packet["readings"], packet["bbox"]
    if (
        not isinstance(readings, list)
        or len(readings) not in (1, 2)
        or not all(isinstance(reading, dict) for reading in readings)
        or tuple(reading.get("dpi") for reading in readings) not in ((400,), (400, 600))
        or not isinstance(bounds, (list, tuple))
        or not any(
            isinstance(reading.get("mask_hex"), str)
            and len(reading["mask_hex"]) > text_limit
            for reading in readings
        )
    ):
        return False

    # No image-engine loading for ordinary text-only diagnostic catalogs.
    from .cell_frame_proof import inside_box
    from .plot_reference_pixels import retained_pixels
    from .source_cell_pixels import MAX_CELL_PIXELS

    if not inside_box(list(bounds), [0, 0, 100000, 100000]):
        return False
    return all(
        retained_pixels(reading, bounds, dpi, MAX_CELL_PIXELS) is not None
        for reading, dpi in zip(readings, (400, 600), strict=False)
    )
