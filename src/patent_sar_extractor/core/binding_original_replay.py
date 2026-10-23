"""One original-document replay entry for every supported structure source kind."""

from .binding_auxiliary_replay import (
    has_binding_auxiliary,
    original_binding_auxiliary_errors,
)
from .caption_locator_source import original_caption_locator_errors
from .caption_original_replay import caption_sources, original_caption_source_errors
from .heading_original_replay import heading_sources, original_heading_source_errors
from .plot_original_replay import original_plot_source_errors, plot_literal_sources
from .role_original_replay import original_role_source_errors


def original_binding_sources(
    bindings, *, role_text=(), plot_references=(), caption_references=()
):
    return bool(
        heading_sources(bindings)
        or caption_sources(bindings)
        or bool(role_text)
        or bool(plot_references)
        or bool(caption_references)
        or has_binding_auxiliary(bindings, role_text=role_text)
    )


def original_binding_source_errors(
    document, bindings, *, role_text=(), plot_references=(), caption_references=()
):
    plot_references = tuple(plot_references)
    plot_errors = original_plot_source_errors(document, plot_references)
    if plot_errors:
        return plot_errors
    caption_errors = original_caption_locator_errors(document, caption_references)
    if caption_errors:
        return caption_errors
    role_text = (*role_text, *plot_literal_sources(plot_references))
    return [
        *original_heading_source_errors(document, bindings),
        *original_caption_source_errors(document, bindings),
        *original_binding_auxiliary_errors(document, bindings, role_text=role_text),
        *original_role_source_errors(document, role_text),
    ]
