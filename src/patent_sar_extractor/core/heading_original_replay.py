"""Read-only original heading replay, without repeating OCR or trusting flags."""

import hashlib

from .cell_raster import original_reading_image
from .heading_source_proof import proved_heading_declaration
from .source_geometry import SourceTokens, source_layout
from .source_observations import source_cell_observation
from .source_paint_visibility import visible_native_tokens

HEADING_RULES = frozenset(
    {"original_heading_standalone", "original_heading_reaction_product"}
)


def validate_original_heading(page, proof):
    """The caller owns the already verified original document and PDF lock."""

    if (
        proved_heading_declaration(proof) is None
        or proof.get("version") not in {1, 2}
        or proof["page_no"] != page.number + 1
        or proof["page_size"] != [page.rect.width, page.rect.height]
    ):
        raise ValueError("Original heading observation cannot be replayed")
    layout = source_layout(page)
    native = source_cell_observation(
        SourceTokens(layout.native, layout), tuple(proof["bbox"]), native=True
    )
    if native != proof["native_source"] or proof["raster_bounds"] != (
        list(layout.raster_bounds) if layout.raster_bounds else None
    ):
        raise ValueError("Original literal heading text or geometry differs")
    if not proof["observations"]:
        if not visible_native_tokens(page, native):
            raise ValueError(
                "Original native heading is invisible, covered or unproved"
            )
        return

    frames = proof["rendered_frames"]
    if not isinstance(frames, list) or len(frames) != 2:
        raise ValueError("Original heading raster observations are incomplete")
    for frame, reading, dpi in zip(
        frames, proof["observations"], (400, 600), strict=True
    ):
        if "source_window" not in reading:
            raise ValueError(
                "Current heading requires its complete original cell window"
            )
        image = original_reading_image(page, proof["bbox"], dpi, reading)
        if frame != {
            "dpi": dpi,
            "shape": list(image.shape),
            "pixel_sha256": hashlib.sha256(image.tobytes()).hexdigest(),
        }:
            raise ValueError(
                "Original heading pixels differ from the recorded observation"
            )
    from .text_ocr.cell_proof import replay_auxiliary_cell
    from .text_ocr.source_inventory import auxiliary_source_cells

    for _, reading in auxiliary_source_cells(
        (proof["page_no"], reading) for reading in proof["observations"]
    ):
        if not replay_auxiliary_cell(reading, page):
            raise ValueError("Auxiliary heading row differs from its original pixels")


def heading_sources(bindings):
    """A removed packet cannot remove the replay requirement of its rule."""
    return [
        b
        for b in bindings
        if b.get("binding_rule") in HEADING_RULES
        or b.get("original_heading_structure_evidence") is not None
    ]


def original_heading_source_errors(document, bindings):
    """One original readback for both standalone and reaction-heading consumers."""
    from .heading_page_replay import HeadingPageReplay
    from .heading_reaction import observe_reaction_source

    errors = []
    original_pages = HeadingPageReplay(document)
    for binding in heading_sources(bindings):
        evidence = binding.get("original_heading_structure_evidence") or {}
        try:
            heading = evidence["heading_source"]
            validate_original_heading(document[heading["page_no"] - 1], heading)
            original_pages.check(evidence["declaration_scope"], heading)
            reaction = evidence.get("reaction_source")
            if (
                reaction is None
                and binding.get("binding_rule") != "original_heading_standalone"
            ):
                raise ValueError("Original reaction source packet is missing")
            if reaction is not None:
                expected = observe_reaction_source(
                    document, evidence["declaration_scope"], heading
                )
                if expected != reaction:
                    raise ValueError(
                        "Native reaction observation differs from original PDF ink"
                    )
        except (KeyError, TypeError, ValueError, RuntimeError, IndexError) as exc:
            errors.append(f"{binding.get('structure_id', '')}: {exc}")
    return errors
