"""Explicit original figure-source inventory, without OCR or a second writer."""

from .heading_source_proof import proved_heading_declaration
from .plot_reference_pixels import replay_pixels
from .role_text_sources import framed_role_cell
from .source_geometry import SourceTokens, source_layout
from .source_observations import source_cell_observation


def plot_reference_sources(payload):
    """Only the existing source ledger can own a figure-role claim."""
    from .binding_source_references import MAX_SOURCE_SECTIONS

    sections = payload.get("source_sections", [])
    if (
        not isinstance(sections, list)
        or len(sections) > MAX_SOURCE_SECTIONS
        or any(not isinstance(section, dict) for section in sections)
    ):
        raise ValueError("Malformed original figure-source owners")
    for section in sections:
        if section.get("role") != "figure_label_reference":
            continue
        proof = section.get("heading_observation")
        declaration = proved_heading_declaration(proof)
        if (
            declaration is None
            or declaration["role"] != "figure_label_reference"
            or type(section.get("page_no")) is not int
            or section.get("page_no") != proof["page_no"]
        ):
            raise ValueError("Missing or unproved original figure-role owner")
        yield proof


def plot_literal_sources(proofs):
    """Known literal owners only, never a recursive search of arbitrary JSON."""
    for proof in proofs:
        cells = list(proof["figure_source"]["literal_cells"])
        locator = proof.get("original_locator")
        if isinstance(locator, dict) and locator.get("version") == 2:
            cells.extend(row["cell"] for row in locator["rows"])
        for cell in cells:
            scope = cell["reading"]
            for index, view in enumerate(scope["observations"]):
                yield (
                    proof["page_no"],
                    framed_role_cell(scope, index, 0, view["cells"][0]),
                )


def _pixel_packets(proof):
    figure = proof["figure_source"]
    yield figure["marker"]
    yield from (figure["axis_strokes"][axis] for axis in ("x", "y"))
    locator = proof.get("original_locator")
    if locator is not None:
        yield locator["pixels"]
    refinement = figure["axis_refinement"]
    if refinement is not None:
        yield from (refinement["axis_strokes"][axis] for axis in ("x", "y"))
        words = refinement.get("word_observations")
        if words is None:
            yield refinement["word_observation"]["pixels"]
        else:
            yield from (words[axis]["pixels"] for axis in ("x", "y"))


def original_plot_source_errors(document, proofs):
    """Recheck the actual parent pixels and native contexts, not saved flags.

    Literal native/optical/auxiliary frames use the existing role-cell replayers
    through plot_literal_sources. No text recognition is repeated here.
    """
    layouts = {}
    try:
        for proof in proofs:
            declaration = proved_heading_declaration(proof)
            if declaration is None or declaration["role"] != "figure_label_reference":
                return ["Original figure source is missing or unproved."]
            page_no = proof["page_no"]
            if page_no > len(document):
                return ["Original figure page is unavailable."]
            page = document[page_no - 1]
            if proof["page_size"] != [page.rect.width, page.rect.height]:
                return ["Original figure page geometry differs."]
            for packet in _pixel_packets(proof):
                for reading in packet["readings"]:
                    replay_pixels(page, packet["bbox"], reading)
            if page_no not in layouts:
                layouts[page_no] = source_layout(page)
            layout = layouts[page_no]
            tokens = SourceTokens(layout.native, layout, layout.raster_bounds)
            for chunk in proof["figure_source"]["chunks"]:
                expected = source_cell_observation(tokens, chunk["bbox"], native=True)
                if (
                    next(p for p in chunk["sources"] if p["origin"] == "native")
                    != expected
                ):
                    return ["Original figure native context differs."]
    except (
        OSError,
        KeyError,
        TypeError,
        ValueError,
        RuntimeError,
        IndexError,
        OverflowError,
    ):
        return ["Original figure source replay is unavailable."]
    return []
