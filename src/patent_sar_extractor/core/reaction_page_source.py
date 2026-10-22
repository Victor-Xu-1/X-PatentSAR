"""Native and retained-pixel adapters into one original reaction graph."""

from .raster_reaction_detail import observe_pixel_page, page_vectors
from .reaction_raster_layout import observe_raster_layout, pixel_source_required
from .reaction_vectors import observe_vectors, validate_vectors


def source_page_vectors(packet, regions, *, original_frame=None):
    if isinstance(packet, dict) and "kind" in packet:
        return page_vectors(packet, regions, original_frame=original_frame)
    validate_vectors(packet)
    if packet["version"] != 2:
        raise ValueError(
            "Binary reaction geometry is missing its original pixel source"
        )
    return packet, {}


def observe_source_page(page, bounds, regions, *, original_frame=None):
    sources = observe_raster_layout(page, bounds)
    if pixel_source_required(sources, regions):
        # A raster body cannot inherit native direction. Account for its
        # complete visible original through the pixel adapter, never vote
        # between two recognizers or retry a different product ranking.
        return observe_pixel_page(
            page, bounds, regions, raster_sources=sources, original_frame=original_frame
        )
    return observe_vectors(page, bounds, original_frame=original_frame)
