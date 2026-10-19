"""Call-local original PDF rendering without inherited decoder tile state."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import fitz


@contextmanager
def isolated_original_page(page: fitz.Page) -> Iterator[fitz.Page]:
    """Reopen the complete source context, not a lossy single-page projection.

    File sources stay lazy; immutable byte sources share their existing input.
    Only an edited/in-memory PDF needs serialization of its current contents.
    No copy is written to disk, no original is edited, and no antialias setting
    or optional-content configuration is changed.
    """
    source = page.parent
    if not source.is_pdf:
        raise ValueError("Original cell rendering requires a PDF source")
    # needs_pass delegates to MuPDF's password probe, which can replace the
    # active decryption key after authentication. Inspect inert trailer metadata
    # instead; never probe credentials while rendering an already loaded page.
    encrypted = source.xref_get_key(-1, "Encrypt")[0] != "null"
    if source.is_dirty or encrypted:
        original = fitz.open(stream=source.tobytes(), filetype="pdf")
    elif source.stream is not None:
        original = fitz.open(stream=source.stream, filetype="pdf")
    else:
        original = fitz.open(source.name)
    with original:
        # Retain the loaded page's actual geometry and visible source state.
        # In particular, insert_pdf alone would lose document-level OCG state.
        # A changed file or transient unpersisted layer state must not silently
        # provide a different original. Normal source-file hash gates still apply.
        target = original[page.number]
        if (target.rect, target.mediabox, target.cropbox, target.rotation) != (
            page.rect,
            page.mediabox,
            page.cropbox,
            page.rotation,
        ) or original.get_ocgs() != source.get_ocgs():
            raise ValueError("Original cell page context differs from its source")
        yield target


def original_cell_pixmap(
    page: fitz.Page, *, matrix: fitz.Matrix, clip: fitz.Rect
) -> fitz.Pixmap:
    """Exactly one bounded clip on a fresh source decoder, closed on all exits."""
    try:
        with isolated_original_page(page) as original:
            return original.get_pixmap(matrix=matrix, clip=clip, alpha=False)
    finally:
        # Closing a PDF does not reclaim every decoded image-tile store entry.
        # Fresh document identities otherwise retain one cache per observation.
        # Reclaim this Python process's recoverable MuPDF store only AFTER the
        # owned decoder closes. Live references and returned pixels stay valid;
        # no source, disk/OS cache, rendering option or other process is changed.
        fitz.TOOLS.store_shrink(100)
