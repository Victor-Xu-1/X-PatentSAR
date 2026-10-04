"""General MDL stereo fixtures, independent of patents and compound identifiers."""

from __future__ import annotations

from rdkit import Chem
from rdkit.Chem import rdDepictor


def structure_block(smiles: str, *, v3000: bool = False) -> str:
    molecule = Chem.MolFromSmiles(smiles)
    rdDepictor.Compute2DCoords(molecule)
    return Chem.MolToMolBlock(molecule, forceV3000=v3000)


def unknown_block(kind: str, *, v3000: bool = False) -> tuple[str, str]:
    smiles = {"tetra": "FC(Cl)Br", "double": "FC=CF", "mixed": "F[C@H](Cl)C(Br)I"}[kind]
    molecule = Chem.MolFromSmiles(smiles)
    rdDepictor.Compute2DCoords(molecule)
    bond = molecule.GetBondWithIdx(3 if kind == "mixed" else 1)
    if kind != "double":
        bond.SetBondDir(Chem.BondDir.UNKNOWN)
    else:
        bond.SetStereo(Chem.BondStereo.STEREOANY)
    return smiles, Chem.MolToMolBlock(molecule, forceV3000=v3000)


def moved_block(block: str, *, v3000: bool = False) -> str:
    molecule = Chem.MolFromMolBlock(block, removeHs=False)
    Chem.ReapplyMolBlockWedging(molecule)
    position = molecule.GetConformer().GetAtomPosition(0)
    molecule.GetConformer().SetAtomPosition(
        0, (position.x + 0.125, position.y + 0.25, position.z)
    )
    return Chem.MolToMolBlock(molecule, forceV3000=v3000)
