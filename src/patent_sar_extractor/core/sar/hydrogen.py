"""Source-preserving one-H graph views, never invented source atom indices."""

from __future__ import annotations

from rdkit import Chem, rdBase

from .errors import SARInputError
from .graphs import graph
from .molecules import chemical_identity
from .regions import selection


def hydrogen_sites(mol: Chem.Mol):
    source = graph(mol)
    blocked = set(source.potential_atoms)
    for index in source.potential_bonds:
        bond = mol.GetBondWithIdx(index)
        blocked.update((bond.GetBeginAtomIdx(), bond.GetEndAtomIdx()))
    return [
        (
            atom.GetTotalNumHs(),
            atom.GetAtomicNum() > 1
            and atom.GetTotalNumHs() > 0
            and not atom.GetNumRadicalElectrons()
            and atom.GetIdx() not in blocked,
        )
        for atom in mol.GetAtoms()
    ]


def hydrogen_view(
    mol: Chem.Mol, anchor: int, *, prepared_sites=None, source_identity=None
) -> tuple[Chem.Mol, int]:
    """Expand one already-present ordinary H at the nominated original atom.

    Isotopic/explicit graph-H neighbours remain original atoms. Only the added
    virtual node is excluded from public original-atom selections. Boundary
    tetrahedral/double-bond stereo is refused until a proven transport exists.
    """
    if type(anchor) is not int or not 0 <= anchor < mol.GetNumAtoms():
        raise SARInputError("hydrogen_site_unavailable")
    atom = mol.GetAtomWithIdx(anchor)
    if (
        atom.GetAtomicNum() <= 1
        or not atom.GetTotalNumHs()
        or atom.GetNumRadicalElectrons()
    ):
        raise SARInputError("hydrogen_site_unavailable")
    sites = prepared_sites if prepared_sites is not None else hydrogen_sites(mol)
    if not sites[anchor][1]:
        raise SARInputError("hydrogen_boundary_stereo_unsupported")
    with rdBase.BlockLogs():
        try:
            editable = Chem.RWMol(mol)
            attached = editable.GetAtomWithIdx(anchor)
            if attached.GetNumExplicitHs():
                attached.SetNumExplicitHs(attached.GetNumExplicitHs() - 1)
            virtual = editable.AddAtom(Chem.Atom(1))
            editable.AddBond(anchor, virtual, Chem.BondType.SINGLE)
            expanded = editable.GetMol()
            Chem.SanitizeMol(expanded)
            Chem.AssignStereochemistry(expanded, cleanIt=False, force=True)
            if chemical_identity(expanded) != (
                source_identity
                if source_identity is not None
                else chemical_identity(mol)
            ):
                raise SARInputError("hydrogen_view_identity")
        except SARInputError:
            raise
        except (ValueError, RuntimeError, OverflowError):
            raise SARInputError("hydrogen_view_unsupported") from None
    return expanded, virtual


def region_view(mol, atom_indices, hydrogen_anchor=None):
    if hydrogen_anchor is None:
        return mol, selection(mol, atom_indices)
    if not isinstance(atom_indices, (list, tuple)) or atom_indices:
        raise SARInputError("region_invalid_indices")
    expanded, virtual = hydrogen_view(mol, hydrogen_anchor)
    return expanded, selection(expanded, [virtual])
