"""Bounded local rendering of a SMILES-derived molecule, never original evidence."""

from __future__ import annotations

import hashlib
from functools import lru_cache
from urllib.parse import quote

from .errors import WebError


def drawing_url(project_id: str, compound_id: str, smiles: str) -> str:
    fingerprint = hashlib.sha256(smiles.encode()).hexdigest()
    return f"/api/v1/projects/{project_id}/structures/{quote(compound_id, safe='')}/redraw?fingerprint={fingerprint}"


@lru_cache(maxsize=128)
def draw_smiles(smiles: str) -> bytes:
    from rdkit import Chem
    from rdkit.Chem.Draw import rdMolDraw2D

    if not isinstance(smiles, str) or not smiles or len(smiles) > 4096:
        raise WebError(
            422, "drawing_limit", "SMILES is empty or exceeds the rendering limit."
        )
    molecule = Chem.MolFromSmiles(smiles)
    if molecule is None:
        raise WebError(
            422, "invalid_smiles", "SMILES cannot be rendered as a valid molecule."
        )
    if molecule.GetNumAtoms() > 512 or molecule.GetNumBonds() > 768:
        raise WebError(
            422, "drawing_limit", "Molecule exceeds the rendering size limit."
        )
    drawer = rdMolDraw2D.MolDraw2DCairo(600, 400)
    rdMolDraw2D.PrepareAndDrawMolecule(drawer, molecule)
    drawer.FinishDrawing()
    rendered = drawer.GetDrawingText()
    if len(rendered) > 2 * 1024 * 1024:
        raise WebError(
            422, "drawing_limit", "Rendered molecule exceeds the byte limit."
        )
    return rendered
