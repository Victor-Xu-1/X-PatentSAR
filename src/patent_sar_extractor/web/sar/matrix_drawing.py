"""Native matrix camera on one source reference, not independent pair scales."""

import math

from ...core.sar.errors import SARInputError
from ...core.sar.molecules import depict, read_molfile
from .preview_alignment import prepare_layout
from .preview_drawing import molecule_bounds, render_molecule
from .preview_models import PreviewDrawingPair, PreviewMoleculeDrawing
from .preview_source import VerifiedPreview


def matrix_drawings(selections: list[VerifiedPreview]):
    reference = read_molfile(selections[0].reference["molfile"])
    depict(reference)
    coordinates = [(p[0], p[1]) for p in reference.GetConformer().GetPositions()]
    layouts = [
        prepare_layout(
            item.reference["molfile"],
            item.candidate["molfile"],
            item.data.region,
            item.proof,
            coordinates,
        )
        for item in selections
    ]
    bounds = molecule_bounds(
        [
            reference,
            *[
                mol
                for layout in layouts
                for mol in (layout.reference, layout.candidate)
            ],
        ]
    )
    baseline, source_points = render_molecule(reference, (), bounds)
    for item, layout in zip(selections, layouts, strict=True):
        first, first_points = render_molecule(
            layout.reference, layout.reference_atoms, bounds
        )
        second, second_points = render_molecule(
            layout.candidate, layout.candidate_atoms, bounds
        )
        if any(
            math.dist(source_points[i], first_points[i]) > 1e-4
            for i in range(reference.GetNumAtoms())
        ) or (
            layout.aligned
            and any(
                math.dist(source_points[a], second_points[b]) > 1e-4
                for a, b in layout.alignment_mapping
            )
        ):
            raise SARInputError("drawing_alignment_coordinates")
        item.data.drawings = PreviewDrawingPair(
            reference=PreviewMoleculeDrawing(id=item.reference["id"], svg=first),
            candidate=PreviewMoleculeDrawing(id=item.candidate["id"], svg=second),
            layout=layout.layout,
            equivalent_mappings=layout.equivalent_mappings,
            reason=layout.reason,
        )
    return PreviewMoleculeDrawing(id=selections[0].reference["id"], svg=baseline)
