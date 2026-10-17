"""One bounded original-region capture for actual and continued column scopes."""

from .source_geometry import native_region
from .source_window_chunks import observe_source_window
from .structure_table_headers import structure_column_pairs
from .table_cells import read_cell
from .unruled_body_scope import body_context_window, body_diagrams, original_body_bottom
from .unruled_scope import scope_axes, scope_headers
from .unruled_structure_sources import label_windows


def observe_region(page, tokens, header, page_diagrams):
    xs, ys = scope_axes(header)
    context = observe_source_window(tokens, body_context_window(header))
    bottom = original_body_bottom(header, context, page_diagrams)
    region = {
        "status": "observed_original_unruled_columns",
        "version": 1,
        "header_scope": header,
        "body_context": context,
        "page_diagrams": page_diagrams,
        "body_bottom": bottom,
        "pair_sources": [],
        "labels": [],
        "diagrams": body_diagrams(header, bottom, page_diagrams),
    }
    for pair, (identifier, _structure) in enumerate(
        structure_column_pairs(scope_headers(header))
    ):
        window = [xs[identifier], ys[1], xs[identifier + 1], bottom]
        chunks = observe_source_window(tokens, window)
        region["pair_sources"].append({"window": window, "chunks": chunks})
        for line in label_windows(chunks, window):
            reading = read_cell(
                page,
                line["window"],
                tokens,
                "id",
                native_region(tokens, line["window"], False),
            )
            region["labels"].append(
                {
                    "pair": pair,
                    "nomination": line,
                    "value": reading.value,
                    "observations": reading.observations,
                    "needs_review": reading.needs_review,
                }
            )
    return region
