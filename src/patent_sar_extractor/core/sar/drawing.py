"""Safe RDKit SVG and selectable coordinates for the immutable atom indices."""

from __future__ import annotations

import math
from typing import Any

from rdkit import rdBase
from rdkit.Chem.Draw import rdMolDraw2D

from .errors import SARInputError
from .molecules import depict, read_molfile

WIDTH, HEIGHT = 1000, 800


def draw_structure(molfile: str) -> dict[str, Any]:
    """Return normalized SVG-screen coordinates; invalid input raises safe codes."""
    mol = read_molfile(molfile)
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
            drawer.DrawMolecule(drawing)
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
