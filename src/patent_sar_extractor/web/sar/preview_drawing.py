"""One matched-pair RDKit projection with shared camera, scale and highlights."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from rdkit import Chem, rdBase
from rdkit.Chem.Draw import rdMolDraw2D
from rdkit.Geometry import Point2D

from ...core.sar.errors import SARInputError
from ...core.sar.molecules import chemical_identity, read_molfile
from .models import Region
from .preview_alignment import PreviewLayout, prepare_layout
from .preview_models import PreviewDrawingPair, PreviewMoleculeDrawing

CANVAS = (480, 320)
HIGHLIGHT = (0.25, 0.80, 0.60)


def camera(layout: PreviewLayout) -> tuple[Point2D, Point2D]:
    return molecule_bounds((layout.reference, layout.candidate))


def molecule_bounds(molecules: Sequence[Chem.Mol]) -> tuple[Point2D, Point2D]:
    points = [point for mol in molecules for point in mol.GetConformer().GetPositions()]
    if any(not math.isfinite(v) or abs(v) > 1e6 for point in points for v in point):
        raise SARInputError("drawing_coordinates_invalid")
    # Shared complete extent includes the changed region, isotopes, salts and
    # label space; neither molecule is independently auto-scaled or clipped.
    return (
        Point2D(min(p[0] for p in points) - 1.2, min(p[1] for p in points) - 1.2),
        Point2D(max(p[0] for p in points) + 1.2, max(p[1] for p in points) + 1.2),
    )


def render_molecule(
    mol: Chem.Mol,
    highlighted: Sequence[int],
    bounds: tuple[Point2D, Point2D],
) -> tuple[str, list[tuple[float, float]]]:
    with rdBase.BlockLogs():
        drawing = rdMolDraw2D.PrepareMolForDrawing(
            mol, addChiralHs=False, wedgeBonds=True, forceCoords=False
        )
        if drawing.GetNumAtoms() != mol.GetNumAtoms() or chemical_identity(
            read_molfile(Chem.MolToMolBlock(drawing))
        ) != chemical_identity(mol):
            raise SARInputError("drawing_chemical_identity_changed")
        width, height = CANVAS
        drawer = rdMolDraw2D.MolDraw2DSVG(width, height)
        options: Any = drawer.drawOptions()
        options.padding = 0
        options.minFontSize = 10
        options.maxFontSize = 20
        drawer.SetScale(width, height, *bounds)
        colors = {index: HIGHLIGHT for index in highlighted}
        bonds = [
            bond.GetIdx()
            for bond in drawing.GetBonds()
            if bond.GetBeginAtomIdx() in colors and bond.GetEndAtomIdx() in colors
        ]
        drawer.DrawMolecule(
            drawing,
            highlightAtoms=list(highlighted),
            highlightBonds=bonds,
            highlightAtomColors=colors,
            highlightBondColors=dict.fromkeys(bonds, HIGHLIGHT),
        )
        drawer.FinishDrawing()
        coordinates = [
            (drawer.GetDrawCoords(i).x, drawer.GetDrawCoords(i).y)
            for i in range(drawing.GetNumAtoms())
        ]
        if any(
            not math.isfinite(x)
            or not math.isfinite(y)
            or not 0 <= x <= width
            or not 0 <= y <= height
            for x, y in coordinates
        ):
            raise SARInputError("drawing_coordinates_invalid")
        return drawer.GetDrawingText().rstrip(), coordinates


def paired_drawings(
    reference: Mapping[str, Any],
    candidate: Mapping[str, Any],
    region: Region,
    proof: Mapping[str, Any],
) -> PreviewDrawingPair:
    layout = prepare_layout(reference["molfile"], candidate["molfile"], region, proof)
    bounds = camera(layout)
    left, points_left = render_molecule(
        layout.reference, layout.reference_atoms, bounds
    )
    right, points_right = render_molecule(
        layout.candidate, layout.candidate_atoms, bounds
    )
    if layout.aligned and any(
        math.dist(points_left[a], points_right[b]) > 1e-4
        for a, b in layout.alignment_mapping
    ):
        raise SARInputError("drawing_alignment_coordinates")
    return PreviewDrawingPair(
        reference=PreviewMoleculeDrawing(id=reference["id"], svg=left),
        candidate=PreviewMoleculeDrawing(id=candidate["id"], svg=right),
        layout=layout.layout,
        equivalent_mappings=layout.equivalent_mappings,
        reason=layout.reason,
    )
