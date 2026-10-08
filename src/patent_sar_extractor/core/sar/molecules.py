"""One SAR parser/chemical identity authority, independent of app limits."""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from typing import Any

from rdkit import Chem, rdBase
from rdkit.Chem import rdDepictor

from .errors import SARInputError
from .limits import MAX_ATOMS, MAX_BONDS, MAX_SMILES_CHARS
from .molfile import inspect_molfile

TETRAHEDRAL = {Chem.ChiralType.CHI_TETRAHEDRAL_CW, Chem.ChiralType.CHI_TETRAHEDRAL_CCW}
DOUBLE_STEREO = {
    Chem.BondStereo.STEREOE,
    Chem.BondStereo.STEREOZ,
    Chem.BondStereo.STEREOCIS,
    Chem.BondStereo.STEREOTRANS,
}


def _finish(mol: Chem.Mol | None) -> Chem.Mol:
    if mol is None:
        raise SARInputError("invalid_structure")
    if not 0 < mol.GetNumAtoms() <= MAX_ATOMS or mol.GetNumBonds() > MAX_BONDS:
        raise SARInputError("structure_limit_exceeded")
    if any(a.HasQuery() or not a.GetAtomicNum() for a in mol.GetAtoms()):
        raise SARInputError("query_or_markush_structure")
    if any(a.GetAtomMapNum() for a in mol.GetAtoms()):
        raise SARInputError("unsupported_atom_mapping")
    if any(
        b.HasQuery()
        or str(b.GetBondType()) not in {"SINGLE", "DOUBLE", "TRIPLE", "AROMATIC"}
        for b in mol.GetBonds()
    ):
        raise SARInputError("unsupported_bond")
    if any(
        a.GetChiralTag() not in TETRAHEDRAL | {Chem.ChiralType.CHI_UNSPECIFIED}
        for a in mol.GetAtoms()
    ):
        raise SARInputError("unsupported_stereochemistry")
    if any(
        g.GetGroupType() != Chem.StereoGroupType.STEREO_ABSOLUTE
        for g in mol.GetStereoGroups()
    ):
        raise SARInputError("unsupported_mdl_stereo")
    Chem.SanitizeMol(mol)
    Chem.AssignStereochemistry(mol, cleanIt=False, force=True)
    potential = Chem.FindPotentialStereo(mol, cleanIt=False, flagPossible=True)
    if any(
        p.type not in {Chem.StereoType.Atom_Tetrahedral, Chem.StereoType.Bond_Double}
        for p in potential
    ):
        raise SARInputError("unsupported_stereochemistry")
    centers = {
        p.centeredOn for p in potential if p.type == Chem.StereoType.Atom_Tetrahedral
    }
    if any(
        a.GetChiralTag() in TETRAHEDRAL and a.GetIdx() not in centers
        for a in mol.GetAtoms()
    ):
        raise SARInputError("invalid_stereo_assignment")
    for bond in mol.GetBonds():
        # MDL readers can silently ignore a wedge on a non-stereogenic endpoint.
        # Such explicitly encoded evidence is unsupported, not plain chemistry.
        encoded_wedge = (
            bond.HasProp("_MolFileBondStereo")
            and bond.GetIntProp("_MolFileBondStereo") in {1, 6}
        ) or (
            bond.HasProp("_MolFileBondCfg")
            and bond.GetIntProp("_MolFileBondCfg") in {1, 3}
        )
        if encoded_wedge and bond.GetBeginAtom().GetChiralTag() not in TETRAHEDRAL:
            raise SARInputError("unsupported_mdl_stereo")
    if any(
        b.GetStereo()
        not in DOUBLE_STEREO | {Chem.BondStereo.STEREONONE, Chem.BondStereo.STEREOANY}
        for b in mol.GetBonds()
    ):
        raise SARInputError("unsupported_stereochemistry")
    directed = {
        b.GetIdx()
        for b in mol.GetBonds()
        if b.GetBondDir() in {Chem.BondDir.ENDUPRIGHT, Chem.BondDir.ENDDOWNRIGHT}
    }
    covered = {
        adj.GetIdx()
        for b in mol.GetBonds()
        if b.GetStereo() in DOUBLE_STEREO
        for atom in (b.GetBeginAtom(), b.GetEndAtom())
        for adj in atom.GetBonds()
    }
    if directed - covered:
        raise SARInputError("unsupported_directional_markup")
    for conformer in mol.GetConformers():
        if conformer.Is3D():
            raise SARInputError("unsupported_molfile_3d")
        if any(
            not math.isfinite(v) or abs(v) > 1e6
            for p in conformer.GetPositions()
            for v in p
        ):
            raise SARInputError("invalid_coordinates")
    return mol


def _parse(parser: Callable[[], Chem.Mol | None], code: str) -> Chem.Mol:
    # Native parse errors contain user chemistry; do not leak them into logs or
    # structured reasons. Never change a global logger configuration.
    with rdBase.BlockLogs():
        try:
            return _finish(parser())
        except SARInputError:
            raise
        except (ValueError, RuntimeError, OverflowError):
            raise SARInputError(code) from None


def read_smiles(raw: object) -> Chem.Mol:
    if raw is None or raw == "":
        raise SARInputError("smiles_missing")
    if not isinstance(raw, str):
        raise SARInputError("invalid_smiles")
    if len(raw) > MAX_SMILES_CHARS:
        raise SARInputError("smiles_limit_exceeded")
    text = raw.strip()
    if not text or re.search(r"\s|\||@(AL|SP|TB|OH|TH)", text):
        raise SARInputError("unsupported_smiles")
    # The native SDK's property annotations incorrectly type booleans as the
    # options class. Keep this dynamic boundary local; core logic stays typed.
    params: Any = Chem.SmilesParserParams()
    params.sanitize, params.removeHs = False, False
    params.allowCXSMILES, params.parseName = False, False
    return _parse(lambda: Chem.MolFromSmiles(text, params), "invalid_smiles")


def read_molfile(raw: object) -> Chem.Mol:
    text = inspect_molfile(raw)
    return _parse(
        lambda: Chem.MolFromMolBlock(
            text, sanitize=False, removeHs=False, strictParsing=True
        ),
        "invalid_molfile",
    )


def chemical_identity(mol: Chem.Mol) -> str:
    """Exact isomeric identity, including every salt/duplicate component.

    Ordinary explicit H notation is normalized, not isotopic hydrogen, charge,
    tautomer, stereo assignment or components. The indexed Molfile is untouched.
    """
    with rdBase.BlockLogs():
        normalized = Chem.RemoveHs(Chem.Mol(mol))
        return Chem.MolToSmiles(normalized, canonical=True, isomericSmiles=True)


def depict(mol: Chem.Mol) -> None:
    """Deterministic coordinates on a caller-owned copy; never renumber atoms."""
    rdDepictor.Compute2DCoords(
        mol,
        canonOrient=True,
        clearConfs=True,
        sampleSeed=0,
        forceRDKit=True,
        useRingTemplates=False,
    )
