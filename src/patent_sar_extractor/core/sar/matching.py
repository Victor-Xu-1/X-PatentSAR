"""Prove only the selected connected variable region changed, or refuse."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from rdkit import Chem

from .errors import MappingLimit, SARInputError
from .graphs import Graph, fixed_mappings, graph
from .hydrogen import hydrogen_sites, hydrogen_view, region_view
from .limits import MAX_HYDROGEN_VIEWS
from .molecules import chemical_identity, read_molfile
from .regions import attachment_groups, attachment_mapping, connected
from .stereo import boundary_supported, preserved


def validate_region(
    molfile: str, atom_indices: Sequence[int], *, hydrogen_anchor=None
) -> int:
    """Return number of cut bonds, or ValueError containing a safe code only."""
    mol = read_molfile(molfile)
    mol, selected = region_view(mol, atom_indices, hydrogen_anchor)
    return sum(
        len(key) * len(values)
        for key, values in attachment_groups(mol, selected).items()
    )


def _result(status: str, *reasons: str) -> dict[str, Any]:
    return {"match_status": status, "reasons": sorted(set(reasons))}


@dataclass(frozen=True, slots=True)
class CompiledReference:
    """Private pre-parsed reference and immutable selection for CPU batch work.

    No persistence, result cache or relaxed batch policy. Each candidate runs
    exactly the same bounded proof as compare_structure.
    """

    _reference: Graph
    _selected: frozenset[int]
    _anchors: frozenset[int]
    _pool: Any = None

    def compare(self, candidate_molfile: str) -> dict[str, Any]:
        return self._compare(candidate_molfile, details=False)

    def compare_details(self, candidate_molfile: str) -> dict[str, Any]:
        """Expose indices only after exhaustive bounded fixed-graph proof.

        Attachment pairs are reference/candidate FIXED atom indices. Harmless
        non-anchor symmetries do not select an arbitrary full embedding.
        """
        result = self._compare(candidate_molfile, details=True)
        result.setdefault("variable_atom_indices", [])
        result.setdefault("attachment_mapping", [])
        return result

    def _compare(self, candidate_molfile: str, *, details: bool) -> dict[str, Any]:
        try:
            candidate = (
                self._pool.read(candidate_molfile)
                if self._pool is not None
                else graph(read_molfile(candidate_molfile))
            )
        except SARInputError as exc:
            return _result("ineligible", "candidate_ineligible", exc.code)
        result = _compare_graphs(
            self._reference, candidate, self._selected, self._anchors, details=details
        )
        fixed_count = self._reference.mol.GetNumAtoms() - len(self._selected)
        ports = attachment_groups(self._reference.mol, self._selected)
        if (
            candidate.mol.GetNumAtoms() != fixed_count
            or sum(len(key) * len(values) for key, values in ports.items()) != 1
        ):
            return result
        accepted, failures = None, set()
        anchor = next(iter(self._anchors))
        required = Counter(
            (bond, self._reference.atoms[index])
            for index, bond in self._reference.adjacency[anchor].items()
            if index not in self._selected
        )
        possible = []
        for index, key in enumerate(candidate.atoms):
            adjusted = (*key[:5], key[5] + 1, key[6] - 1, key[7])
            if (
                key[0] > 1
                and key[6] > 0
                and adjusted == self._reference.atoms[anchor]
                and required
                == Counter(
                    (bond, candidate.atoms[other])
                    for other, bond in candidate.adjacency[index].items()
                )
            ):
                possible.append(index)
        if len(possible) > MAX_HYDROGEN_VIEWS:
            return _result("ambiguous", "hydrogen_view_limit_exceeded")
        if not possible:
            return result
        sites, identity = (
            hydrogen_sites(candidate.mol),
            chemical_identity(candidate.mol),
        )
        for index in possible:
            atom = candidate.mol.GetAtomWithIdx(index)
            try:
                expanded, virtual = hydrogen_view(
                    candidate.mol,
                    atom.GetIdx(),
                    prepared_sites=sites,
                    source_identity=identity,
                )
            except SARInputError as error:
                failures.add(error.code)
                continue
            proof = _compare_graphs(
                self._reference,
                graph(expanded),
                self._selected,
                self._anchors,
                details=True,
            )
            if proof["match_status"] == "ambiguous":
                return _result("ambiguous", *proof["reasons"])
            if proof["match_status"] != "matched":
                failures.update(proof["reasons"])
                continue
            if proof["variable_atom_indices"] != [virtual]:
                raise SARInputError("hydrogen_view_identity")
            signature = tuple(map(tuple, proof["attachment_mapping"]))
            if accepted is not None and accepted[0] != signature:
                return _result("ambiguous", "ambiguous_region_mapping")
            accepted = (signature, atom.GetIdx())
        if accepted is None:
            return _result("not_matched", *(failures or result["reasons"]))
        proof = _result("matched")
        if details:
            proof.update(
                variable_atom_indices=[],
                attachment_mapping=[list(pair) for pair in accepted[0]],
                candidate_hydrogen_anchor=accepted[1],
            )
        return proof


def compile_reference(
    reference_molfile: str,
    atom_indices: Sequence[int],
    *,
    hydrogen_anchor=None,
    pool=None,
) -> CompiledReference:
    """Optional pure worker helper; invalid references raise safe ValueError."""
    prepared = (
        pool.read(reference_molfile)
        if pool is not None
        else graph(read_molfile(reference_molfile))
    )
    mol, selected = region_view(prepared.mol, atom_indices, hydrogen_anchor)
    reference = prepared if mol is prepared.mol else graph(mol)
    if not boundary_supported(reference, selected):
        raise SARInputError("unsupported_boundary_bond_stereo")
    anchors = frozenset(
        endpoint
        for key in attachment_groups(reference.mol, selected)
        for endpoint, _ in key
    )
    return CompiledReference(reference, selected, anchors, pool)


def _compare_graphs(
    reference: Graph,
    candidate: Graph,
    selected: frozenset[int],
    anchors: frozenset[int],
    *,
    details: bool = False,
    membership: bool = False,
) -> dict[str, Any]:
    if len(Chem.GetMolFrags(reference.mol)) != len(Chem.GetMolFrags(candidate.mol)):
        return _result("not_matched", "components_changed")
    fixed_count = reference.mol.GetNumAtoms() - len(selected)
    if candidate.mol.GetNumAtoms() < fixed_count or (
        not membership and candidate.mol.GetNumAtoms() == fixed_count
    ):
        return _result("not_matched", "candidate_variable_empty")
    failures, proof = set(), None
    try:
        for mapping in fixed_mappings(reference, candidate, selected):
            remaining = frozenset(range(candidate.mol.GetNumAtoms())) - frozenset(
                mapping.values()
            )
            if not membership and not connected(candidate.mol, remaining):
                failures.add("candidate_variable_disconnected")
                continue
            ports = attachment_mapping(
                reference.mol, candidate.mol, selected, remaining, mapping
            )
            if ports is None:
                failures.add("attachment_endpoints_changed")
                continue
            if not boundary_supported(candidate, remaining):
                raise SARInputError("unsupported_boundary_bond_stereo")
            if not preserved(reference, candidate, mapping, ports):
                failures.add("fixed_stereo_changed")
                continue
            # Descriptive core membership needs existence, not a chosen location.
            # Every embedding still passes identical ports/stereo/bounds; no
            # candidate mapping is exposed for this deliberately separate role.
            signature = (
                (frozenset(), ())
                if membership
                else (remaining, tuple((i, mapping[i]) for i in sorted(anchors)))
            )
            if proof is not None and signature != proof:
                return _result("ambiguous", "ambiguous_region_mapping")
            proof = signature
    except MappingLimit as exc:
        return _result("ambiguous", str(exc))
    except SARInputError as exc:
        return _result("ineligible", exc.code)
    if proof is None:
        return _result("not_matched", *(failures or {"fixed_graph_changed"}))
    result = _result("matched")
    if details:
        result.update(
            variable_atom_indices=sorted(proof[0]),
            attachment_mapping=[list(pair) for pair in proof[1]],
        )
    return result


def compare_structure(
    reference_molfile: str, candidate_molfile: str, atom_indices: Sequence[int]
) -> dict[str, Any]:
    """Whole fixed graph, port endpoints, components and stereo are mandatory.

    Symmetric embeddings are harmless only when every proved embedding selects
    the same candidate region AND the same fixed attachment endpoints. No first
    embedding is chosen; incomplete bounded search is always ambiguous.
    """
    try:
        matcher = compile_reference(reference_molfile, atom_indices)
    except SARInputError as exc:
        return _result("ineligible", "reference_ineligible", exc.code)
    return matcher.compare(candidate_molfile)
