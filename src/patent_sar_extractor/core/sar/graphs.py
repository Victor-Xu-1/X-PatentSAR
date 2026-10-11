"""Bounded exact induced fixed-graph embeddings, not similarity or MCS proof."""

from __future__ import annotations

from collections import Counter, OrderedDict
from collections.abc import Iterator
from dataclasses import dataclass

from rdkit import Chem

from .errors import MappingLimit
from .graph_features import GraphFacts, prepare_facts
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
    by_key: dict[AtomKey, tuple[int, ...]]
    neighbor_keys: tuple[Counter, ...]
    neighbor_masks: tuple[int, ...]
    facts: GraphFacts


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
    keyed = {}
    for index, key in enumerate(atoms):
        keyed.setdefault(key, []).append(index)
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
        {key: tuple(indices) for key, indices in keyed.items()},
        tuple(
            Counter((bond, atoms[other]) for other, bond in links.items())
            for links in adjacency
        ),
        tuple(sum(1 << other for other in links) for links in adjacency),
        prepare_facts(mol),
    )


class FixedAtoms:
    """Reference-only constraints and at most eight exact traversal orders.

    This caches preparation, never embeddings or scientific results. Domain
    lengths alone determine traversal; all actual domains/edges stay checked.
    """

    def __init__(self, reference: Graph, selected: frozenset[int]):
        self.reference, self.selected = reference, selected
        self.fixed = frozenset(range(len(reference.atoms))) - selected
        self.nodes = tuple(sorted(self.fixed))
        self.required = {
            index: tuple(
                sorted(
                    Counter(
                        (bond, reference.atoms[other])
                        for other, bond in reference.adjacency[index].items()
                        if other in self.fixed
                    ).items()
                )
            )
            for index in self.nodes
        }
        self._orders = OrderedDict()

    def order(self, domains):
        signature = tuple(len(domains[index]) for index in self.nodes)
        if signature not in self._orders:
            order, unplaced = [], set(self.fixed)
            frontiers = dict.fromkeys(self.fixed, 0)
            while unplaced:
                node = min(
                    unplaced,
                    key=lambda index: (
                        -frontiers[index],
                        len(domains[index]),
                        -len(self.reference.adjacency[index]),
                        index,
                    ),
                )
                order.append(node)
                unplaced.remove(node)
                for neighbor in self.reference.adjacency[node]:
                    if neighbor in unplaced:
                        frontiers[neighbor] += 1
            self._orders[signature] = tuple(order)
            if len(self._orders) > 8:
                self._orders.popitem(last=False)
        else:
            self._orders.move_to_end(signature)
        return self._orders[signature]


def fixed_mappings(
    reference: Graph,
    candidate: Graph,
    selected: frozenset[int],
    *,
    prepared: FixedAtoms | None = None,
) -> Iterator[dict[int, int]]:
    """Yield at most 64 complete embeddings; any further proof is ambiguous.

    Work is counted deterministically, including rejected assignments. Degrees
    and H counts describe the original full molecule, not a sanitized fragment.
    """
    prepared = prepared if prepared is not None else FixedAtoms(reference, selected)
    if prepared.reference is not reference or prepared.selected != selected:
        raise ValueError("fixed_preparation_identity")
    domains = {}
    for i in prepared.nodes:
        required = prepared.required[i]
        domains[i] = tuple(
            index
            for index in candidate.by_key.get(reference.atoms[i], ())
            if all(
                amount <= candidate.neighbor_keys[index][key]
                for key, amount in required
            )
        )
    if any(not domain for domain in domains.values()):
        return
    # Visit connected frontiers first to keep long common linkers inexpensive.
    order = prepared.order(domains)
    mapping: dict[int, int] = {}
    used = 0
    states = completed = 0

    def visit(position: int) -> Iterator[dict[int, int]]:
        nonlocal states, completed, used
        if position == len(order):
            if completed == MAX_MAPPINGS:
                raise MappingLimit("mapping_limit_exceeded")
            completed += 1
            yield dict(mapping)
            return
        node = order[position]
        allowed = None
        attached = [
            (mapping[other], bond)
            for other, bond in reference.adjacency[node].items()
            if other in mapping
        ]
        expected_neighbors = sum(1 << target for target, _ in attached)
        for target, _ in attached:
            neighbors = set(candidate.adjacency[target])
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
            bit = 1 << target
            # The bitset proves BOTH edges and nonedges to every placed atom;
            # bond keys then prove the exact types of all required edges.
            if (
                used & bit
                or (candidate.neighbor_masks[target] & used != expected_neighbors)
                or any(
                    bond != candidate.adjacency[target].get(mapped)
                    for mapped, bond in attached
                )
            ):
                continue
            mapping[node] = target
            used |= bit
            yield from visit(position + 1)
            used ^= bit
            del mapping[node]

    yield from visit(0)
