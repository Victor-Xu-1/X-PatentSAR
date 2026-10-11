"""Transport tetrahedral and double-bond parity through an actual atom map.

Do not compare raw @/indices or unqualified R/S: variable substituents can change
CIP priorities without changing the fixed center's physical configuration.
"""

from __future__ import annotations

from rdkit import Chem

from .errors import SARInputError
from .graphs import Graph
from .molecules import DOUBLE_STEREO, TETRAHEDRAL
from .regions import PortMap


def boundary_supported(graph: Graph, variable: frozenset[int]) -> bool:
    return not any(
        (graph.facts.bonds[index].begin in variable)
        != (graph.facts.bonds[index].end in variable)
        for index in graph.potential_bonds
    )


def _mapped(index: int, anchor: int, mapping: dict[int, int], ports: PortMap) -> int:
    if index in mapping:
        return mapping[index]
    if (anchor, index) in ports:
        return ports[anchor, index]
    raise SARInputError("unsupported_boundary_stereo")


def _permutation_sign(left: list[int], right: list[int]) -> int:
    if set(left) != set(right) or len(left) != len(right):
        raise SARInputError("unsupported_boundary_stereo")
    permutation = [right.index(item) for item in left]
    odd = (
        sum(
            permutation[i] > permutation[j]
            for i in range(len(left))
            for j in range(i + 1, len(left))
        )
        % 2
    )
    return -1 if odd else 1


def _tetrahedral(
    reference: Graph, candidate: Graph, mapping: dict[int, int], ports: PortMap
) -> bool:
    for source, target in mapping.items():
        if (source in reference.potential_atoms) != (
            target in candidate.potential_atoms
        ):
            return False
        a, b = reference.facts.chiral_tags[source], candidate.facts.chiral_tags[target]
        if (a in TETRAHEDRAL) != (b in TETRAHEDRAL):
            return False
        if a not in TETRAHEDRAL:
            continue
        # Degree-three tetrahedra have the implicit H/remaining ligand last on
        # both sides; full atom keys prove degree, valence and H are unchanged.
        if reference.atoms[source][5] not in {3, 4}:
            raise SARInputError("unsupported_tetrahedral_stereo")
        neighbors = [
            _mapped(index, source, mapping, ports)
            for index in reference.facts.neighbors[source]
        ]
        sign = _permutation_sign(neighbors, list(candidate.facts.neighbors[target]))
        if (a == b) != (sign == 1):
            return False
    return True


def _double_sign(stereo: Chem.BondStereo) -> int:
    return 1 if stereo in {Chem.BondStereo.STEREOE, Chem.BondStereo.STEREOTRANS} else -1


def _double_bonds(
    reference: Graph, candidate: Graph, mapping: dict[int, int], ports: PortMap
) -> bool:
    if not (
        reference.potential_bonds
        or candidate.potential_bonds
        or reference.facts.defined_double
        or candidate.facts.defined_double
    ):
        return True
    for left in reference.facts.bonds:
        begin, end = left.begin, left.end
        if begin not in mapping or end not in mapping:
            continue
        right = candidate.facts.by_edge[tuple(sorted((mapping[begin], mapping[end])))]
        if (left.index in reference.potential_bonds) != (
            right.index in candidate.potential_bonds
        ):
            return False
        a, b = left.stereo in DOUBLE_STEREO, right.stereo in DOUBLE_STEREO
        if a != b:
            return False
        if not a:
            continue
        carriers, other_carriers = left.carriers, right.carriers
        if len(carriers) != 2 or len(other_carriers) != 2:
            raise SARInputError("unsupported_double_bond_stereo")
        candidate_carriers = dict(zip((right.begin, right.end), other_carriers))
        sign = _double_sign(left.stereo)
        for endpoint, other_endpoint, carrier in (
            (begin, end, carriers[0]),
            (end, begin, carriers[1]),
        ):
            actual = candidate_carriers[mapping[endpoint]]
            expected = _mapped(carrier, endpoint, mapping, ports)
            if actual != expected:
                alternatives = set(candidate.facts.neighbors[mapping[endpoint]]) - {
                    mapping[other_endpoint]
                }
                if alternatives != {actual, expected}:
                    raise SARInputError("unsupported_boundary_stereo")
                sign *= -1
        if sign != _double_sign(right.stereo):
            return False
    return True


def preserved(
    reference: Graph, candidate: Graph, mapping: dict[int, int], ports: PortMap
) -> bool:
    return _tetrahedral(reference, candidate, mapping, ports) and _double_bonds(
        reference, candidate, mapping, ports
    )
