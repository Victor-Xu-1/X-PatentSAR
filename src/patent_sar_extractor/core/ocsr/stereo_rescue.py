"""Pure bounded graph/stereo guard, never source/image acceptance.

Caller owns source QC/native hard deadline; no model/image or raw/cache/record writes.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from time import monotonic

from rdkit import Chem
from rdkit.Chem import rdCIPLabeler

from .smiles_qc import COMMON_FINAL_PRODUCT_ELEMENTS, qc_smiles

MAX_SMILES_CHARS, MAX_ATOMS, MAX_BONDS, MAX_FRAGMENTS = 4096, 128, 192, 8
MAX_MAPPINGS, MAX_SEARCH_STATES = 64, 20000
MAX_CIP_ITERATIONS = 50000
PRIMARY_FLAG = "stereochemistry_not_retained"


class _Refused(ValueError):
    """Explicit refusal reason, optionally carrying completed mapping count."""


@dataclass(frozen=True)
class _Graph:
    mol: Chem.Mol
    keys: tuple
    adjacency: tuple
    fragments: int
    raw_atoms: frozenset[int]
    raw_bonds: frozenset[tuple[int, int]]
    atom_stereo: tuple
    bond_stereo: dict


def stereo_rescue_eligible(primary_quality_flag: object) -> bool:
    """Cheap caller preflight only; validation independently rechecks primary QC."""
    return type(primary_quality_flag) is str and primary_quality_flag == PRIMARY_FLAG


def _decision(eligible, accepted, reason, count=0):
    return {
        "eligible": eligible,
        "accepted": accepted,
        "reason": reason,
        "mappings_checked": count,
    }


def _check_time(deadline):
    if monotonic() >= deadline:
        raise _Refused("time_budget_exceeded")


def _tokens(raw):
    return len(re.findall(r"\[[^\]\s]*@", raw)), raw.count("/") + raw.count("\\")


def _edge(left, right):
    return tuple(sorted((left, right)))


def _assign_cip(mol, deadline):
    _check_time(deadline)
    for item in (*mol.GetAtoms(), *mol.GetBonds()):
        item.ClearProp("_CIPCode")
    Chem.AssignStereochemistry(mol, cleanIt=True, force=True)
    try:
        rdCIPLabeler.AssignCIPLabels(mol, maxRecursiveIterations=MAX_CIP_ITERATIONS)
    except Exception as exc:
        raise _Refused("cip_assignment_failed") from exc
    _check_time(deadline)


def _observe(raw, deadline):
    _check_time(deadline)
    if type(raw) is not str or not raw:
        raise _Refused("invalid_smiles_input")
    if len(raw) > MAX_SMILES_CHARS:
        raise _Refused("input_budget_exceeded")
    if re.search(r"\s|\||@(AL|SP|TB|OH|TH)", raw):
        raise _Refused("unsupported_smiles")
    params = Chem.SmilesParserParams()
    params.sanitize, params.removeHs = False, False
    params.allowCXSMILES, params.parseName = False, False
    mol = Chem.MolFromSmiles(raw, params)
    if mol is None:
        raise _Refused("invalid_smiles_input")
    fragments = len(Chem.GetMolFrags(mol))
    if (
        mol.GetNumAtoms() > MAX_ATOMS
        or mol.GetNumBonds() > MAX_BONDS
        or fragments > MAX_FRAGMENTS
    ):
        raise _Refused("input_budget_exceeded")
    tetra = {Chem.ChiralType.CHI_TETRAHEDRAL_CW, Chem.ChiralType.CHI_TETRAHEDRAL_CCW}
    marked = frozenset(a.GetIdx() for a in mol.GetAtoms() if a.GetChiralTag() in tetra)
    allowed = {"SINGLE", "DOUBLE", "TRIPLE", "AROMATIC"}
    if any(
        a.HasQuery()
        or a.GetAtomMapNum()
        or a.GetSymbol() not in COMMON_FINAL_PRODUCT_ELEMENTS
        or a.GetChiralTag() not in tetra | {Chem.ChiralType.CHI_UNSPECIFIED}
        for a in mol.GetAtoms()
    ) or any(
        b.HasQuery() or str(b.GetBondType()) not in allowed for b in mol.GetBonds()
    ):
        raise _Refused("unsupported_smiles")
    directions = {
        b.GetIdx()
        for b in mol.GetBonds()
        if b.GetBondDir() in {Chem.BondDir.ENDUPRIGHT, Chem.BondDir.ENDDOWNRIGHT}
    }
    covered, directed = set(), set()
    for bond in mol.GetBonds():
        if bond.GetBondType() != Chem.BondType.DOUBLE:
            continue
        ends = [
            {b.GetIdx() for b in atom.GetBonds() if b.GetIdx() in directions}
            for atom in (bond.GetBeginAtom(), bond.GetEndAtom())
        ]
        if all(ends):
            covered.update(ends[0] | ends[1])
            directed.add(_edge(bond.GetBeginAtomIdx(), bond.GetEndAtomIdx()))
    if covered != directions:
        raise _Refused("unsupported_directional_markup")
    Chem.SanitizeMol(mol)
    if mol.GetStereoGroups() or any(a.GetNumRadicalElectrons() for a in mol.GetAtoms()):
        raise _Refused("unsupported_smiles")
    _assign_cip(mol, deadline)
    atoms = tuple(
        a.GetProp("_CIPCode") if a.HasProp("_CIPCode") else None for a in mol.GetAtoms()
    )
    bonds = {
        _edge(b.GetBeginAtomIdx(), b.GetEndAtomIdx()): b.GetProp("_CIPCode")
        for b in mol.GetBonds()
        if b.HasProp("_CIPCode")
    }
    if any(label not in {None, "R", "S", "r", "s"} for label in atoms) or any(
        label not in {"E", "Z"} for label in bonds.values()
    ):
        raise _Refused("unsupported_stereochemistry")
    _check_time(deadline)
    qc = qc_smiles(raw)
    _check_time(deadline)
    if (
        sum(label is not None for label in atoms) != qc["assigned_chiral_centers"]
        or len(bonds) != qc["assigned_double_bonds"]
    ):
        raise _Refused("stereo_perception_mismatch")
    # Keep isotopes and explicit H nodes. No isomericSmiles=False shortcut.
    keys, adjacency = [], []
    for atom in mol.GetAtoms():
        idx = atom.GetIdx()
        identity = atom.GetAtomicNum(), atom.GetIsotope(), atom.GetFormalCharge()
        keys.append(identity + (atom.GetIsAromatic(), atom.GetTotalNumHs()))
        neighbors = {}
        for b in atom.GetBonds():
            neighbors[b.GetOtherAtomIdx(idx)] = str(b.GetBondType()), b.GetIsAromatic()
        adjacency.append(neighbors)
    keys, adjacency, directed = tuple(keys), tuple(adjacency), frozenset(directed)
    return _Graph(mol, keys, adjacency, fragments, marked, directed, atoms, bonds), qc


def _mapping_stereo(primary, candidate, mapping):
    atoms = tuple(candidate.atom_stereo[mapping[i]] for i in range(len(primary.keys)))
    bonds = {
        _edge(i, j): candidate.bond_stereo.get(_edge(mapping[i], mapping[j]))
        for i, linked in enumerate(primary.adjacency)
        for j in linked
        if i < j
    }
    if any(
        label is not None and atoms[i] != label
        for i, label in enumerate(primary.atom_stereo)
    ):
        return "retained_atom_stereo_conflict"
    if any(bonds[edge] != label for edge, label in primary.bond_stereo.items()):
        return "retained_bond_stereo_conflict"
    if any(atoms[i] is None for i in primary.raw_atoms) or any(
        bonds[edge] is None for edge in primary.raw_bonds
    ):
        raise _Refused("raw_stereo_not_restored")
    return atoms, tuple(sorted(bonds.items()))


def _all_mappings(primary, candidate, deadline, max_mappings, max_states):
    def colors(graph):
        for i, key in enumerate(graph.keys):
            links = graph.adjacency[i].items()
            yield key, tuple(sorted((bond, graph.keys[j]) for j, bond in links))

    if (
        len(primary.keys) != len(candidate.keys)
        or primary.fragments != candidate.fragments
    ):
        raise _Refused("graph_mismatch")
    left, right = tuple(colors(primary)), tuple(colors(candidate))
    domains = [[j for j, color in enumerate(right) if color == key] for key in left]
    if any(not domain for domain in domains):
        raise _Refused("graph_mismatch")
    order = sorted(
        range(len(left)), key=lambda i: (len(domains[i]), -len(primary.adjacency[i]))
    )
    mapping, used = {}, set()
    checked, states, signature = 0, 0, None
    last_conflict = None
    lost = primary.raw_atoms - {
        i for i, label in enumerate(primary.atom_stereo) if label
    }
    rings = tuple(frozenset(r) for r in primary.mol.GetRingInfo().AtomRings())
    if (
        not lost
        or any(not any(i in r for r in rings) for i in lost)
        or primary.raw_bonds - primary.bond_stereo.keys()
    ):
        raise _Refused("unsupported_lost_stereo")
    dependencies = {}

    def additions(current):
        atoms, bonds = current
        if any(label and edge not in primary.raw_bonds for edge, label in bonds):
            raise _Refused("unrequested_bond_stereo")
        for i, label in enumerate(atoms):
            if not label or primary.atom_stereo[i] or i in primary.raw_atoms:
                continue
            partners = {
                j for j in lost if any(i in ring and j in ring for ring in rings)
            }
            if not partners:
                raise _Refused("unrelated_atom_stereo")
            target = mapping[i]
            if target not in dependencies:
                copy = Chem.Mol(candidate.mol)
                copy.GetAtomWithIdx(target).SetChiralTag(
                    Chem.ChiralType.CHI_UNSPECIFIED
                )
                _assign_cip(copy, deadline)
                dependencies[target] = {
                    a.GetIdx() for a in copy.GetAtoms() if not a.HasProp("_CIPCode")
                }
            if not any(mapping[j] in dependencies[target] for j in partners):
                raise _Refused("nonessential_ring_stereo")

    def visit(depth):
        nonlocal checked, states, signature, last_conflict
        _check_time(deadline)
        if depth == len(order):
            if checked >= max_mappings:
                raise _Refused("mapping_budget_exceeded")
            checked += 1
            current = _mapping_stereo(primary, candidate, mapping)
            if isinstance(current, str):
                last_conflict = current
                return
            additions(current)
            if signature is not None and current != signature:
                raise _Refused("ambiguous_stereo_mapping")
            signature = current
            return
        i = order[depth]
        for j in domains[i]:
            _check_time(deadline)
            states += 1
            if states > max_states:
                raise _Refused("search_budget_exceeded")
            if j in used or any(
                primary.adjacency[i].get(k) != candidate.adjacency[j].get(v)
                for k, v in mapping.items()
            ):
                continue
            mapping[i] = j
            used.add(j)
            visit(depth + 1)
            used.remove(j)
            del mapping[i]

    try:
        visit(0)
    except _Refused as exc:
        raise _Refused(exc.args[0], checked) from None
    if not checked:
        raise _Refused("graph_mismatch")
    if signature is None:
        raise _Refused(last_conflict, checked)
    return checked


def validate_stereo_rescue(
    primary_raw: str,
    candidate_raw: str,
    *,
    primary_quality_flag: str,
    timeout_seconds: float = 0.5,
    max_mappings: int = MAX_MAPPINGS,
    max_search_states: int = MAX_SEARCH_STATES,
) -> dict:
    """Require exact graph and unanimous stereo among retained-compatible maps.

    Refuse depleted budgets, unpreserved raw intent and inconsistent survivors.
    """
    if not stereo_rescue_eligible(primary_quality_flag):
        return _decision(False, False, "primary_not_eligible")
    if (
        type(timeout_seconds) not in {int, float}
        or not math.isfinite(timeout_seconds)
        or not 0 < timeout_seconds <= 2
        or type(max_mappings) is not int
        or not 0 < max_mappings <= MAX_MAPPINGS
        or type(max_search_states) is not int
        or not 0 < max_search_states <= MAX_SEARCH_STATES
    ):
        return _decision(False, False, "invalid_budget")
    eligible = False
    deadline = monotonic() + timeout_seconds
    try:
        primary, primary_qc = _observe(primary_raw, deadline)
        if primary_qc["quality_flag"] != PRIMARY_FLAG or not primary_qc["rdkit_valid"]:
            raise _Refused("primary_quality_mismatch")
        eligible = True
        candidate, candidate_qc = _observe(candidate_raw, deadline)
        if candidate_qc["quality_flag"] != "ok" or not candidate_qc["rdkit_valid"]:
            raise _Refused("candidate_not_clean")
        canonical = candidate_qc["isomeric_smiles"]
        if not canonical or _tokens(candidate_raw) != _tokens(canonical):
            raise _Refused("candidate_markup_not_retained")
        raw_tokens, clean_tokens = _tokens(primary_raw), _tokens(canonical)
        if any(p > c for p, c in zip(raw_tokens, clean_tokens, strict=True)):
            raise _Refused("raw_stereo_tokens_dropped")
        count = _all_mappings(
            primary, candidate, deadline, max_mappings, max_search_states
        )
        _check_time(deadline)
        return _decision(True, True, "compatible_stereo_candidate", count)
    except _Refused as exc:
        return _decision(
            eligible, False, exc.args[0], exc.args[1] if len(exc.args) > 1 else 0
        )
    except (RuntimeError, ValueError, TypeError, KeyError):
        return _decision(eligible, False, "validation_failed")
