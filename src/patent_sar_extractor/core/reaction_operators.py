"""Literal native addition operators through the shared original-cell authority.

No OCR or chemistry model runs here. A raster/hidden/overpainted native word is
not promoted into an observed operator. Whole operator ownership is replayed
from the current original by the same heading source reader.
"""

from .native_cell_replay import original_native_cell_matches
from .native_paint_geometry import valid_native_paint
from .reaction_arrows import contained
from .reaction_vectors import valid_rectangle
from .source_geometry import SourceTokens, overlaps, source_layout
from .source_observations import source_cell_observation, source_observation_status
from .source_paint_visibility import native_paint_view

MAX_NATIVE_OPERATORS = 512


def validate_native_operators(cells, vectors, protected):
    if not isinstance(cells, list) or len(cells) > MAX_NATIVE_OPERATORS:
        raise ValueError("Original reaction operator inventory exceeds its bound")
    seen = set()
    for cell in cells:
        if (
            vectors["version"] != 2
            or not isinstance(cell, dict)
            or set(cell) != {"method", "bbox", "text", "source_observation"}
            or cell["method"] != "native_cell"
            or cell["text"] != "+"
            or not valid_rectangle(cell["bbox"], vectors["page_size"])
            or not contained(cell["bbox"], vectors["bounds"])
            or any(overlaps(cell["bbox"], region) for region in protected)
            or cell["bbox"] not in vectors["blockers"]
            or source_observation_status(cell["source_observation"], cell["bbox"], "+")
            != "qualified"
        ):
            raise ValueError(
                "Reaction operator lacks its complete literal native source"
            )
        source = cell["source_observation"]
        if (
            source.get("schema_version") != 2
            or source["origin"] != "native"
            or len(source["tokens"]) != 1
            or not valid_native_paint(source["tokens"][0])
            or tuple(cell["bbox"]) in seen
        ):
            raise ValueError(
                "Reaction operator has foreign, duplicate or missing native paint"
            )
        seen.add(tuple(cell["bbox"]))


def observe_native_operators(page, vectors, protected):
    if vectors["version"] != 2:
        return []
    layout = source_layout(page)
    nominations = [
        word
        for word in layout.native
        if word["text"] == "+"
        and contained(word["bbox"], vectors["bounds"])
        and not any(overlaps(word["bbox"], region) for region in protected)
    ]
    if len(nominations) > MAX_NATIVE_OPERATORS:
        raise ValueError("Original reaction operator inventory exceeds its bound")
    if not nominations:
        return []
    tokens, paints = (
        SourceTokens(layout.native, layout, layout.raster_bounds),
        native_paint_view(page),
    )
    cells = []
    for word in nominations:
        cell = {
            "method": "native_cell",
            "bbox": list(word["bbox"]),
            "text": "+",
            "source_observation": source_cell_observation(
                tokens, word["bbox"], native=True
            ),
        }
        if not original_native_cell_matches(
            page, cell, layout=layout, paint_view=paints
        ):
            raise ValueError(
                "Literal reaction operator is not visible in its original source"
            )
        cells.append(cell)
    validate_native_operators(cells, vectors, protected)
    return cells
