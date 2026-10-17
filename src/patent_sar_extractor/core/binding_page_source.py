"""Complete binding source views from the sole shared page-observation cache."""

from pathlib import Path

from .binding_source_lines import merged_source_lines, source_line_map
from .page_ocr_cache import (
    load_page_ocr_cache,
    update_page_ocr_cache,
    validate_page_source,
)
from .page_ocr_execution import PageObservationError
from .source_geometry import native_lines, source_layout


def binding_page_source(doc, pdf_path, cache_path, workers, profile_lines):
    """A missing cache is observed once; an existing cache is never overwritten."""
    path = Path(cache_path)
    if path.is_file():
        cache = load_page_ocr_cache(str(path))
    elif path.exists():
        raise ValueError("Original binding page cache is not a file")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        cache = update_page_ocr_cache(
            pdf_path,
            list(range(len(doc))),
            str(path),
            workers=workers,
            min_native_chars=0,
            retry_empty=False,
        )
    try:
        validate_page_source(pdf_path, cache)
    except PageObservationError as error:
        raise ValueError(
            "Original binding page cache identity or coverage is invalid"
        ) from error
    lines = source_line_map(cache["ocr_line_map"])
    for index in range(len(doc)):
        text = cache["page_texts"][str(index)]
        if lines.get(index):
            if not text.strip():
                raise PageObservationError(
                    f"Empty binding page {index + 1} contradicts original source lines"
                )
            continue
        page = doc[index]
        layout = source_layout(page)
        if not text.strip():
            if layout.native:
                raise PageObservationError(
                    f"Empty binding page {index + 1} contradicts original native text"
                )
            continue
        if (
            layout.native
            and layout.raster_bounds is None
            and text.split() == page.get_text("text").split()
        ):
            # A read-only projection from this original native page. Do not
            # add provenance to, or rewrite, a saved raw cache.
            lines[index] = native_lines(layout)
        else:
            raise PageObservationError(
                f"Original binding page {index + 1} lacks complete source coordinates"
            )
    return cache, merged_source_lines(profile_lines, lines)
