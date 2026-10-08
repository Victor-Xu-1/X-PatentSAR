"""Transport tetrahedral and double-bond parity through an actual atom map.

Do not compare raw @/indices or unqualified R/S: variable substituents can change
CIP priorities without changing the fixed center's physical configuration.
"""

from __future__ import annotations

from rdkit import Chem

from .errors import SARInputError
from .graphs import Graph
from .molecules import DOUBLE_STEREO, TETRAHEDRAL


def boundary_supported(graph: Graph, variable: frozenset[int]) -> bool:
    return not any(
        b.GetIdx() in graph.potential_bonds
        and ((b.GetBeginAtomIdx() in variable) != (b.GetEndAtomIdx() in variable))
        for b in graph.mol.GetBonds()
    )


def _mapped(index: int, mapping: dict[int, int], ports: dict[int, int]) -> int:
    if index in mapping:
        return mapping[index]
    if index in ports:
        return ports[index]
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
    reference: Graph, candidate: Graph, mapping: dict[int, int], ports: dict[int, int]
) -> bool:
    for source, target in mapping.items():
        if (source in reference.potential_atoms) != (
            target in candidate.potential_atoms
        ):
            return False
        left, right = (
            reference.mol.GetAtomWithIdx(source),
            candidate.mol.GetAtomWithIdx(target),
        )
        a, b = left.GetChiralTag(), right.GetChiralTag()
        if (a in TETRAHEDRAL) != (b in TETRAHEDRAL):
            return False
        if a not in TETRAHEDRAL:
            continue
        # Degree-three tetrahedra have the implicit H/remaining ligand last on
        # both sides; full atom keys prove degree, valence and H are unchanged.
        if left.GetDegree() not in {3, 4}:
            raise SARInputError("unsupported_tetrahedral_stereo")
        neighbors = [
            _mapped(atom.GetIdx(), mapping, ports) for atom in left.GetNeighbors()
        ]
        sign = _permutation_sign(
            neighbors, [atom.GetIdx() for atom in right.GetNeighbors()]
        )
        if (a == b) != (sign == 1):
            return False
    return True


def _double_sign(bond: Chem.Bond) -> int:
    return (
        1
        if bond.GetStereo() in {Chem.BondStereo.STEREOE, Chem.BondStereo.STEREOTRANS}
        else -1
    )


def _double_bonds(
    reference: Graph, candidate: Graph, mapping: dict[int, int], ports: dict[int, int]
) -> bool:
    for left in reference.mol.GetBonds():
        begin, end = left.GetBeginAtomIdx(), left.GetEndAtomIdx()
        if begin not in mapping or end not in mapping:
            continue
        right = candidate.mol.GetBondBetweenAtoms(mapping[begin], mapping[end])
        if (left.GetIdx() in reference.potential_bonds) != (
            right.GetIdx() in candidate.potential_bonds
        ):
            return False
        a, b = left.GetStereo() in DOUBLE_STEREO, right.GetStereo() in DOUBLE_STEREO
        if a != b:
            return False
        if not a:
            continue
        carriers = list(left.GetStereoAtoms())
        other_carriers = list(right.GetStereoAtoms())
        if len(carriers) != 2 or len(other_carriers) != 2:
            raise SARInputError("unsupported_double_bond_stereo")
        candidate_carriers = dict(
            zip((right.GetBeginAtomIdx(), right.GetEndAtomIdx()), other_carriers)
        )
        sign = _double_sign(left)
        for endpoint, other_endpoint, carrier in (
            (begin, end, carriers[0]),
            (end, begin, carriers[1]),
        ):
            actual = candidate_carriers[mapping[endpoint]]
            expected = _mapped(carrier, mapping, ports)
            if actual != expected:
                alternatives = {
                    atom.GetIdx()
                    for atom in candidate.mol.GetAtomWithIdx(
                        mapping[endpoint]
                    ).GetNeighbors()
                } - {mapping[other_endpoint]}
                if alternatives != {actual, expected}:
                    raise SARInputError("unsupported_boundary_stereo")
                sign *= -1
        if sign != _double_sign(right):
            return False
    return True


def preserved(
    reference: Graph, candidate: Graph, mapping: dict[int, int], ports: dict[int, int]
) -> bool:
    return _tetrahedral(reference, candidate, mapping, ports) and _double_bonds(
        reference, candidate, mapping, ports
    )
