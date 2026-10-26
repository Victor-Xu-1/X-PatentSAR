"""Original numbered-source replay in the single binding acceptance path."""

from itertools import chain

from .caption_tail_sources import caption_tail_text_cells
from .text_ocr.cell_proof import has_auxiliary_text, replay_auxiliary_cell
from .text_ocr.source_inventory import auxiliary_source_cells, physical_text_sources


def binding_text_cells(bindings):
    """Known source owners only; no recursive search of arbitrary artifact data."""
    for binding in bindings:
        sources = [
            binding.get("exact_caption_evidence"),
            binding.get("numbered_table_cell_evidence"),
        ]
        heading = binding.get("original_heading_structure_evidence")
        if isinstance(heading, dict):
            source = heading.get("heading_source")
            if isinstance(source, dict):
                sources.extend((source, source.get("original_heading")))
        for source in sources:
            if isinstance(source, dict):
                for reading in source.get("observations", []):
                    yield source.get("page_no"), reading
    yield from caption_tail_text_cells(bindings)


def has_binding_auxiliary(bindings, *, role_text=()):
    return any(
        has_auxiliary_text(cell)
        for _, cell in physical_text_sources(
            chain(binding_text_cells(bindings), role_text)
        )
    )


def original_binding_auxiliary_errors(document, bindings, *, role_text=()):
    try:
        for page_no, cell in auxiliary_source_cells(
            chain(binding_text_cells(bindings), role_text)
        ):
            if page_no > len(document) or not replay_auxiliary_cell(
                cell, document[page_no - 1]
            ):
                return ["Auxiliary binding text differs from its original page pixels."]
    except (KeyError, TypeError, ValueError, RuntimeError, IndexError) as exc:
        return [f"Auxiliary binding source replay is unavailable: {exc}"]
    return []
