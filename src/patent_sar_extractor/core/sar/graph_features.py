"""Immutable full-source bond/stereo facts, prepared once without normalization."""

from dataclasses import dataclass

from rdkit import Chem

from .molecules import DOUBLE_STEREO


@dataclass(frozen=True, slots=True)
class BondFacts:
    index: int
    begin: int
    end: int
    aromatic: bool
    stereo: Chem.BondStereo
    carriers: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class GraphFacts:
    chiral_tags: tuple[Chem.ChiralType, ...]
    neighbors: tuple[tuple[int, ...], ...]
    bonds: tuple[BondFacts, ...]
    by_edge: dict[tuple[int, int], BondFacts]
    components: int
    defined_double: tuple[int, ...]


def prepare_facts(mol: Chem.Mol) -> GraphFacts:
    atoms = tuple(mol.GetAtoms())
    bonds = tuple(
        BondFacts(
            bond.GetIdx(),
            bond.GetBeginAtomIdx(),
            bond.GetEndAtomIdx(),
            bond.GetIsAromatic(),
            bond.GetStereo(),
            tuple(bond.GetStereoAtoms()),
        )
        for bond in mol.GetBonds()
    )
    return GraphFacts(
        tuple(atom.GetChiralTag() for atom in atoms),
        tuple(tuple(other.GetIdx() for other in atom.GetNeighbors()) for atom in atoms),
        bonds,
        {tuple(sorted((bond.begin, bond.end))): bond for bond in bonds},
        len(Chem.GetMolFrags(mol)),
        tuple(bond.index for bond in bonds if bond.stereo in DOUBLE_STEREO),
    )
