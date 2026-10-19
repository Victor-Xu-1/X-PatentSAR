"""One original-document replay entry for every supported structure source kind."""

from .binding_auxiliary_replay import (
    has_binding_auxiliary,
    original_binding_auxiliary_errors,
)
from .caption_original_replay import caption_sources, original_caption_source_errors
from .heading_original_replay import heading_sources, original_heading_source_errors


def original_binding_sources(bindings):
    return bool(
        heading_sources(bindings)
        or caption_sources(bindings)
        or has_binding_auxiliary(bindings)
    )


def original_binding_source_errors(document, bindings):
    return [
        *original_heading_source_errors(document, bindings),
        *original_caption_source_errors(document, bindings),
        *original_binding_auxiliary_errors(document, bindings),
    ]
