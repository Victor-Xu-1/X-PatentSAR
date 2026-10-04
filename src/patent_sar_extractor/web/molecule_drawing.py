"""Bounded SMILES/manual-MDL rendering, never original image evidence."""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from urllib.parse import quote

from .correction_chemistry import (
    molfile_molecule,
    validate_molfile_text,
    validate_structure,
)
from .errors import WebError


def drawing_fingerprint(smiles: str, molfile: str | None = None) -> str:
    # Preserve exact legacy URL identity when there is no manual representation.
    if molfile is None:
        return hashlib.sha256(smiles.encode()).hexdigest()
    validate_molfile_text(molfile)
    payload = json.dumps(
        ["manual-mdl-v1", smiles, molfile], ensure_ascii=False, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def drawing_url(
    project_id: str, compound_id: str, smiles: str, molfile: str | None = None
) -> str:
    fingerprint = drawing_fingerprint(smiles, molfile)
    return f"/api/v1/projects/{project_id}/structures/{quote(compound_id, safe='')}/redraw?fingerprint={fingerprint}"


@lru_cache(maxsize=32)
def draw_smiles(smiles: str, molfile: str | None = None) -> bytes:
    from rdkit import Chem
    from rdkit.Chem.Draw import rdMolDraw2D

    if not isinstance(smiles, str) or not smiles or len(smiles) > 4096:
        raise WebError(
            422, "drawing_limit", "SMILES is empty or exceeds the rendering limit."
        )
    if molfile is None:
        molecule = Chem.MolFromSmiles(smiles)
    else:
        try:
            validate_structure(molfile, smiles)
            molecule = molfile_molecule(molfile)
        except ValueError as exc:
            raise WebError(
                422,
                "invalid_manual_structure",
                "Manual MDL drawing failed exact validation.",
            ) from exc
    if molecule is None:
        raise WebError(
            422, "invalid_smiles", "SMILES cannot be rendered as a valid molecule."
        )
    if molecule.GetNumAtoms() > 512 or molecule.GetNumBonds() > 768:
        raise WebError(
            422, "drawing_limit", "Molecule exceeds the rendering size limit."
        )
    drawer = rdMolDraw2D.MolDraw2DCairo(600, 400)
    if molfile is None:
        rdMolDraw2D.PrepareAndDrawMolecule(drawer, molecule)
    else:
        # Parsing/assignment clears directions. Restore only original MDL flags,
        # preserving unknown bonds and supplied coordinates, never re-wedging.
        Chem.ReapplyMolBlockWedging(molecule)
        molecule = rdMolDraw2D.PrepareMolForDrawing(
            molecule,
            addChiralHs=False,
            wedgeBonds=False,
            forceCoords=False,
        )
        # RDKit's stubs incorrectly type these documented boolean setters.
        options = drawer.drawOptions()
        setattr(options, "prepareMolsBeforeDrawing", False)
        setattr(options, "includeChiralFlagLabel", True)
        drawer.DrawMolecule(molecule)
    drawer.FinishDrawing()
    rendered = drawer.GetDrawingText()
    if not isinstance(rendered, bytes):
        raise WebError(422, "drawing_protocol", "Drawing backend did not return PNG bytes.")
    if len(rendered) > 2 * 1024 * 1024:
        raise WebError(
            422, "drawing_limit", "Rendered molecule exceeds the byte limit."
        )
    return rendered
