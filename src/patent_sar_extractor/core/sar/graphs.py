"""Bounded exact induced fixed-graph embeddings, not similarity or MCS proof."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass

from rdkit import Chem

from .errors import MappingLimit
from .limits import MAX_MAPPINGS, MAX_SEARCH_STATES
from .regions import BondKey, bond_key

AtomKey = tuple[int, int, int, bool, int, int, int, int]


@dataclass(frozen=True)
class Graph:
    mol: Chem.Mol
    atoms: tuple[AtomKey, ...]
    adjacency: tuple[dict[int, BondKey], ...]
    potential_atoms: frozenset[int]
    potential_bonds: frozenset[int]


def graph(mol: Chem.Mol) -> Graph:
    atoms = tuple(
        (
            a.GetAtomicNum(),
            a.GetIsotope(),
            a.GetFormalCharge(),
            a.GetIsAromatic(),
            a.GetNumRadicalElectrons(),
            a.GetDegree(),
            a.GetTotalNumHs(),
            a.GetTotalValence(),
        )
        for a in mol.GetAtoms()
    )
    adjacency = tuple(
        {b.GetOtherAtomIdx(a.GetIdx()): bond_key(b) for b in a.GetBonds()}
        for a in mol.GetAtoms()
    )
    potential = Chem.FindPotentialStereo(mol, cleanIt=False, flagPossible=True)
    return Graph(
        mol,
        atoms,
        adjacency,
        frozenset(
            p.centeredOn
            for p in potential
            if p.type == Chem.StereoType.Atom_Tetrahedral
        ),
        frozenset(
            p.centeredOn for p in potential if p.type == Chem.StereoType.Bond_Double
        ),
    )


def fixed_mappings(
    reference: Graph, candidate: Graph, selected: frozenset[int]
) -> Iterator[dict[int, int]]:
    """Yield at most 64 complete embeddings; any further proof is ambiguous.

    Work is counted deterministically, including rejected assignments. Degrees
    and H counts describe the original full molecule, not a sanitized fragment.
    """
    fixed = frozenset(range(len(reference.atoms))) - selected
    colors = [
        Counter((bond, candidate.atoms[j]) for j, bond in links.items())
        for links in candidate.adjacency
    ]
    domains = {}
    for i in sorted(fixed):
        required = Counter(
            (bond, reference.atoms[j])
            for j, bond in reference.adjacency[i].items()
            if j in fixed
        )
        domains[i] = tuple(
            j
            for j, key in enumerate(candidate.atoms)
            if reference.atoms[i] == key and not required - colors[j]
        )
    if any(not domain for domain in domains.values()):
        return
    # Visit connected frontiers first to keep long common linkers inexpensive.
    order, unplaced = [], set(fixed)
    while unplaced:
        next_atom = min(
            unplaced,
            key=lambda i: (
                -sum(j in order for j in reference.adjacency[i]),
                len(domains[i]),
                -len(reference.adjacency[i]),
                i,
            ),
        )
        order.append(next_atom)
        unplaced.remove(next_atom)
    mapping: dict[int, int] = {}
    used: set[int] = set()
    states = completed = 0

    def visit(position: int) -> Iterator[dict[int, int]]:
        nonlocal states, completed
        if position == len(order):
            if completed == MAX_MAPPINGS:
                raise MappingLimit("mapping_limit_exceeded")
            completed += 1
            yield dict(mapping)
            return
        node = order[position]
        allowed = None
        for other in reference.adjacency[node]:
            if other in mapping:
                neighbors = set(candidate.adjacency[mapping[other]])
                allowed = neighbors if allowed is None else allowed & neighbors
        choices = (
            domains[node]
            if allowed is None
            else (j for j in domains[node] if j in allowed)
        )
        for target in choices:
            states += 1
            if states > MAX_SEARCH_STATES:
                raise MappingLimit("mapping_search_limit_exceeded")
            if target in used or any(
                reference.adjacency[node].get(other)
                != candidate.adjacency[target].get(mapped)
                for other, mapped in mapping.items()
            ):
                continue
            mapping[node] = target
            used.add(target)
            yield from visit(position + 1)
            used.remove(target)
            del mapping[node]

    yield from visit(0)
