"""Unit-only renderer injection: no original-source or geometry acceptance claim."""

import hashlib
from types import SimpleNamespace


def controlled_cell_pixels(image):
    """Keep OCR-layout fixtures explicit while real-PDF tests verify geometry."""

    def capture(_page, _bounds, dpi, **_options):
        return SimpleNamespace(
            image=image,
            frame={
                "dpi": dpi,
                "shape": list(image.shape),
                "pixel_sha256": hashlib.sha256(image.tobytes()).hexdigest(),
            },
            source_window=None,
        )

    return capture
