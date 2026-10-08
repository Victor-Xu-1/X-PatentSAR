"""Safe RDKit SVG and selectable coordinates for the immutable atom indices."""

from __future__ import annotations

import math
from typing import Any

from rdkit import Chem, rdBase
from rdkit.Chem.Draw import rdMolDraw2D

from .errors import SARInputError
from .molecules import depict, read_molfile

WIDTH, HEIGHT = 1000, 800


def draw_structure(
    molfile: str, *, highlighted_atoms: list[int] | None = None
) -> dict[str, Any]:
    """Return normalized SVG-screen coordinates; invalid input raises safe codes."""
    mol = read_molfile(molfile)
    return _draw(mol, highlighted_atoms or [])


def draw_fragment(smiles: str) -> str:
    """Render a recorded scaffold/port-labelled fragment, not an eligible molecule."""
    if not isinstance(smiles, str) or not 1 <= len(smiles) <= 8192:
        raise SARInputError("fragment_drawing_invalid")
    with rdBase.BlockLogs():
        mol = Chem.MolFromSmiles(smiles)
    if mol is None or not 1 <= mol.GetNumAtoms() <= 512:
        raise SARInputError("fragment_drawing_invalid")
    return _draw(mol, [])["svg"]


def _draw(mol, highlighted_atoms: list[int]) -> dict[str, Any]:
    if any(
        type(index) is not int or not 0 <= index < mol.GetNumAtoms()
        for index in highlighted_atoms
    ):
        raise SARInputError("drawing_highlight_invalid")
    try:
        with rdBase.BlockLogs():
            depict(mol)
            drawing = rdMolDraw2D.PrepareMolForDrawing(
                mol, addChiralHs=False, wedgeBonds=True, forceCoords=False
            )
            drawer = rdMolDraw2D.MolDraw2DSVG(WIDTH, HEIGHT)
            # Native drawing-option properties have incomplete SDK annotations.
            options: Any = drawer.drawOptions()
            options.padding = 0.08
            colors = {index: (0.25, 0.80, 0.60) for index in highlighted_atoms}
            bonds = [
                bond.GetIdx()
                for bond in drawing.GetBonds()
                if bond.GetBeginAtomIdx() in colors and bond.GetEndAtomIdx() in colors
            ]
            drawer.DrawMolecule(
                drawing,
                highlightAtoms=highlighted_atoms,
                highlightBonds=bonds,
                highlightAtomColors=colors,
                highlightBondColors={index: (0.25, 0.80, 0.60) for index in bonds},
            )
            drawer.FinishDrawing()
            atoms = []
            for atom in mol.GetAtoms():
                point = drawer.GetDrawCoords(atom.GetIdx())
                x, y = point.x / WIDTH, point.y / HEIGHT
                if not all(math.isfinite(v) and 0 <= v <= 1 for v in (x, y)):
                    raise SARInputError("drawing_coordinates_invalid")
                atoms.append(
                    {
                        "index": atom.GetIdx(),
                        "element": atom.GetSymbol(),
                        "x": x,
                        "y": y,
                    }
                )
            return {"svg": drawer.GetDrawingText().rstrip(), "atoms": atoms}
    except SARInputError:
        raise
    except (ValueError, RuntimeError, OverflowError):
        raise SARInputError("structure_drawing_failed") from None
