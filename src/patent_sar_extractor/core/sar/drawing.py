"""Safe RDKit SVG and selectable coordinates for the immutable atom indices."""

from __future__ import annotations

import math
from typing import Any

from rdkit import Chem, rdBase
from rdkit.Chem.Draw import rdMolDraw2D

from .errors import SARInputError
from .fragment_graphs import read_graph_notation
from .hydrogen import hydrogen_sites, hydrogen_view
from .molecules import depict, read_molfile

WIDTH, HEIGHT = 1000, 800
FRAGMENT_CANVAS = (360, 240)
MOLECULE_PREVIEW_CANVAS = (360, 288)


def draw_structure(
    molfile: str, *, highlighted_atoms: list[int] | None = None
) -> dict[str, Any]:
    """Return normalized SVG-screen coordinates; invalid input raises safe codes."""
    mol = read_molfile(molfile)
    return _draw(mol, highlighted_atoms or [])


def draw_fragment(smiles: str | None, *, graph_smiles: str | None = None) -> str:
    """Render a recorded scaffold/port-labelled fragment, not an eligible molecule."""
    if graph_smiles is not None:
        if smiles is not None:
            raise SARInputError("fragment_drawing_invalid")
        mol = read_graph_notation(graph_smiles)
        if mol.GetNumAtoms() > 512:
            raise SARInputError("fragment_drawing_invalid")
        return _draw(mol, [], canvas=FRAGMENT_CANVAS, graph_only=True)["svg"]
    if not isinstance(smiles, str) or not 1 <= len(smiles) <= 8192:
        raise SARInputError("fragment_drawing_invalid")
    with rdBase.BlockLogs():
        mol = Chem.MolFromSmiles(smiles)
    if mol is None or not 1 <= mol.GetNumAtoms() <= 512:
        raise SARInputError("fragment_drawing_invalid")
    return _draw(mol, [], canvas=FRAGMENT_CANVAS)["svg"]


def draw_molecule_preview(
    molfile: str, *, highlighted_atoms: list[int] | None = None, hydrogen_anchor=None
) -> str:
    """Size passive vectors for cards; selectable maps keep their original canvas."""
    mol = read_molfile(molfile)
    highlighted = highlighted_atoms or []
    if hydrogen_anchor is not None:
        mol, virtual = hydrogen_view(mol, hydrogen_anchor)
        highlighted = [virtual]
    return _draw(
        mol,
        highlighted,
        canvas=MOLECULE_PREVIEW_CANVAS,
    )["svg"]


def _draw(
    mol,
    highlighted_atoms: list[int],
    *,
    canvas: tuple[int, int] = (WIDTH, HEIGHT),
    graph_only=False,
) -> dict[str, Any]:
    width, height = canvas
    if any(
        type(index) is not int or not 0 <= index < mol.GetNumAtoms()
        for index in highlighted_atoms
    ):
        raise SARInputError("drawing_highlight_invalid")
    try:
        with rdBase.BlockLogs():
            depict(mol)
            drawing = rdMolDraw2D.PrepareMolForDrawing(
                mol,
                addChiralHs=False,
                wedgeBonds=True,
                forceCoords=False,
                kekulize=not graph_only,
            )
            drawer = rdMolDraw2D.MolDraw2DSVG(width, height)
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
            if graph_only:
                return {"svg": drawer.GetDrawingText().rstrip(), "atoms": []}
            atoms = []
            sites = hydrogen_sites(mol)
            for atom in mol.GetAtoms():
                point = drawer.GetDrawCoords(atom.GetIdx())
                x, y = point.x / width, point.y / height
                if not all(math.isfinite(v) and 0 <= v <= 1 for v in (x, y)):
                    raise SARInputError("drawing_coordinates_invalid")
                atoms.append(
                    {
                        "index": atom.GetIdx(),
                        "element": atom.GetSymbol(),
                        "x": x,
                        "y": y,
                        "ordinary_hydrogens": sites[atom.GetIdx()][0],
                        "hydrogen_site_supported": bool(sites[atom.GetIdx()][1]),
                    }
                )
            return {"svg": drawer.GetDrawingText().rstrip(), "atoms": atoms}
    except SARInputError:
        raise
    except (ValueError, RuntimeError, OverflowError):
        raise SARInputError("structure_drawing_failed") from None
