"""Read-only MDL stereo semantics; coordinates never establish absolute chirality."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator

from rdkit import Chem

GroupSnapshot = tuple[tuple[int, tuple[int, ...], tuple[int, ...]], ...]
StereoSnapshot = tuple[
    tuple[tuple[int, int], ...], tuple[tuple[int, int], ...], GroupSnapshot
]


def atoms(molecule: Chem.Mol) -> Iterator[Chem.Atom]:
    return (molecule.GetAtomWithIdx(index) for index in range(molecule.GetNumAtoms()))


def bonds(molecule: Chem.Mol) -> Iterator[Chem.Bond]:
    return (molecule.GetBondWithIdx(index) for index in range(molecule.GetNumBonds()))


def unknown_bonds(molecule: Chem.Mol) -> tuple[int, ...]:
    return tuple(
        bond.GetIdx()
        for bond in bonds(molecule)
        if bond.GetStereo() == Chem.BondStereo.STEREOANY
        or bond.GetBondDir() in {Chem.BondDir.UNKNOWN, Chem.BondDir.EITHERDOUBLE}
        or (bond.HasProp("_UnknownStereo") and bond.GetIntProp("_UnknownStereo") != 0)
        or (bond.HasProp("_MolFileBondCfg") and bond.GetIntProp("_MolFileBondCfg") == 2)
        or (
            bond.HasProp("_MolFileBondStereo")
            and bond.GetIntProp("_MolFileBondStereo") in {3, 4}
        )
    )


def explicit_unknown_atoms(molecule: Chem.Mol) -> set[int]:
    """Single starts and double endpoints governed by explicit MDL unknown stereo."""
    targets: set[int] = set()
    for index in unknown_bonds(molecule):
        bond = molecule.GetBondWithIdx(index)
        if bond.GetBondType() == Chem.BondType.SINGLE:
            targets.add(bond.GetBeginAtomIdx())
        elif bond.GetBondType() == Chem.BondType.DOUBLE:
            targets.update((bond.GetBeginAtomIdx(), bond.GetEndAtomIdx()))
    return targets | {
        atom.GetIdx()
        for atom in atoms(molecule)
        if any(
            atom.HasProp(key) and atom.GetIntProp(key) == 3
            for key in ("molParity", "_MolFileAtomParity")
        )
    }


def comparable_groups(molecule: Chem.Mol) -> GroupSnapshot:
    # Some native writers add a STEABS membership/parity to a wavy center.
    # RDKit correctly clears that atom's definite tag. Compare only retained
    # definite membership; the exact raw collection stays in the saved MDL.
    unknown = explicit_unknown_atoms(molecule)
    return tuple(
        (int(group.GetGroupType()), atoms, tuple(b.GetIdx() for b in group.GetBonds()))
        for group in molecule.GetStereoGroups()
        if (
            atoms := tuple(
                a.GetIdx() for a in group.GetAtoms() if a.GetIdx() not in unknown
            )
        )
    )


def stereo_snapshot(molecule: Chem.Mol) -> StereoSnapshot:
    """Encoded defined/unknown/group information that sanitization must retain."""
    return (
        tuple(
            (a.GetIdx(), int(a.GetChiralTag()))
            for a in atoms(molecule)
            if a.GetChiralTag() != Chem.ChiralType.CHI_UNSPECIFIED
        ),
        tuple(
            (
                b.GetIdx(),
                int(
                    {
                        Chem.BondStereo.STEREOCIS: Chem.BondStereo.STEREOZ,
                        Chem.BondStereo.STEREOTRANS: Chem.BondStereo.STEREOE,
                    }.get(b.GetStereo(), b.GetStereo())
                ),
            )
            for b in bonds(molecule)
            if b.GetStereo() != Chem.BondStereo.STEREONONE
        ),
        tuple(
            (
                int(g.GetGroupType()),
                tuple(a.GetIdx() for a in g.GetAtoms()),
                tuple(b.GetIdx() for b in g.GetBonds()),
            )
            for g in molecule.GetStereoGroups()
        ),
    )


def unresolved_stereo_key(molecule: Chem.Mol) -> str | None:
    """A coordinate-independent explicit-MDL ambiguity key, not a prediction graph.

    Atom ranks establish correspondence inside the supplied graph, not between
    an image and a model string. No source conflict or R/S assignment is inferred.
    """
    # Plain unspecified stereo already belongs to the legacy SMILES graph.
    # A normal coordinate-only MDL addition must not add a new semantic gate.
    unknown = unknown_bonds(molecule)
    atom_unknown = tuple(
        a.GetIdx()
        for a in atoms(molecule)
        if any(
            a.HasProp(key) and a.GetIntProp(key) == 3
            for key in ("molParity", "_MolFileAtomParity")
        )
    )
    if not unknown and not atom_unknown:
        return None
    ranks = list(Chem.CanonicalRankAtoms(molecule, includeChirality=True))

    def bond_key(index: int) -> tuple[int, int, int]:
        bond = molecule.GetBondWithIdx(index)
        return (
            int(bond.GetBondType()),
            ranks[bond.GetBeginAtomIdx()],
            ranks[bond.GetEndAtomIdx()],
        )

    encoded = {
        "unknown_bonds": sorted(bond_key(index) for index in unknown),
        "unknown_atoms": sorted(ranks[index] for index in atom_unknown),
    }
    return hashlib.sha256(
        json.dumps(encoded, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def validate_stereo_encoding(molecule: Chem.Mol, text: str) -> None:
    """Reject MDL semantics outside the bounded manual tetrahedral/EZ path."""
    if any(
        a.GetChiralTag()
        not in {
            Chem.ChiralType.CHI_UNSPECIFIED,
            Chem.ChiralType.CHI_TETRAHEDRAL_CW,
            Chem.ChiralType.CHI_TETRAHEDRAL_CCW,
        }
        for a in atoms(molecule)
    ):
        raise ValueError("Only tetrahedral atom stereo is supported")
    if any(
        atom.HasProp(key) and atom.GetIntProp(key) not in {0, 1, 2, 3}
        for atom in atoms(molecule)
        for key in ("molParity", "_MolFileAtomParity")
    ):
        raise ValueError("Unsupported MDL atom parity")
    for bond in bonds(molecule):
        if bond.GetStereo() not in {
            Chem.BondStereo.STEREONONE,
            Chem.BondStereo.STEREOANY,
            Chem.BondStereo.STEREOE,
            Chem.BondStereo.STEREOZ,
            Chem.BondStereo.STEREOCIS,
            Chem.BondStereo.STEREOTRANS,
        }:
            raise ValueError("Unsupported bond stereochemistry")
        if bond.HasProp("_MolFileBondCfg"):
            code = bond.GetIntProp("_MolFileBondCfg")
            allowed = (
                {0, 1, 2, 3} if bond.GetBondType() == Chem.BondType.SINGLE else {0, 2}
            )
            if code not in allowed:
                raise ValueError("Unsupported MDL bond CFG")
        if bond.HasProp("_MolFileBondStereo"):
            code = bond.GetIntProp("_MolFileBondStereo")
            allowed = (
                {0, 1, 4, 6}
                if bond.GetBondType() == Chem.BondType.SINGLE
                else {0, 3}
                if bond.GetBondType() == Chem.BondType.DOUBLE
                else {0}
            )
            if code not in allowed:
                raise ValueError("Unsupported MDL bond stereo")
    groups = molecule.GetStereoGroups()
    unknown_atoms = explicit_unknown_atoms(molecule)
    potential_atoms = {
        item.centeredOn
        for item in Chem.FindPotentialStereo(molecule, cleanIt=False, flagPossible=True)
        if item.type == Chem.StereoType.Atom_Tetrahedral
    }
    # Native writers may attach redundant atom parity/STEABS to an explicitly
    # unknown stereogenic double bond. Never infer a tetrahedral atom or E/Z.
    unknown = set(unknown_bonds(molecule))
    for item in Chem.FindPotentialStereo(molecule, cleanIt=False, flagPossible=True):
        if item.type == Chem.StereoType.Bond_Double and item.centeredOn in unknown:
            bond = molecule.GetBondWithIdx(item.centeredOn)
            potential_atoms.update((bond.GetBeginAtomIdx(), bond.GetEndAtomIdx()))
    encoded_groups = [
        line.split()[2]
        for line in text.splitlines()
        if line.startswith("M  V30 MDLV30/")
    ]
    if any(group != "MDLV30/STEABS" for group in encoded_groups) or len(
        encoded_groups
    ) != len(groups):
        raise ValueError("Unsupported or unretained enhanced stereo collection")
    for group in groups:
        if group.GetGroupType() != Chem.StereoGroupType.STEREO_ABSOLUTE:
            raise ValueError(
                "OR/AND enhanced stereo is not representable by plain SMILES"
            )
        if (
            not group.GetAtoms()
            or group.GetBonds()
            or any(
                a.GetChiralTag() == Chem.ChiralType.CHI_UNSPECIFIED
                and not (a.GetIdx() in unknown_atoms and a.GetIdx() in potential_atoms)
                for a in group.GetAtoms()
            )
        ):
            raise ValueError(
                "Absolute stereo groups require defined tetrahedral centers"
            )
