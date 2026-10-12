"""Presentation-only coordinates from the existing complete fixed-graph proof.

No MCS, substructure-first match, atom renumbering or scientific result is used.
Equivalent fixed automorphisms are exhausted, then source-index order chooses a
layout only; this does not claim a unique chemical atom correspondence.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from rdkit import Chem, rdBase
from rdkit.Chem import rdDepictor

from ...core.sar.errors import SARInputError
from ...core.sar.graphs import fixed_mappings, graph
from ...core.sar.hydrogen import region_view
from ...core.sar.molecules import chemical_identity, depict, read_molfile
from ...core.sar.regions import attachment_mapping
from ...core.sar.stereo import preserved
from .models import Region


@dataclass(frozen=True, slots=True)
class PreviewLayout:
    reference: Chem.Mol
    candidate: Chem.Mol
    reference_atoms: tuple[int, ...]
    candidate_atoms: tuple[int, ...]
    mapping: tuple[tuple[int, int], ...]
    equivalent_mappings: int
    aligned: bool


def prepare_layout(
    reference_molfile: str,
    candidate_molfile: str,
    region: Region,
    proof: Mapping[str, Any],
) -> PreviewLayout:
    """Called only after immutable member/fragment/published-proof verification."""
    if proof.get("match_status") != "matched":
        raise SARInputError("drawing_alignment_proof")
    reference, selected = region_view(
        read_molfile(reference_molfile), region.atom_indices, region.hydrogen_anchor
    )
    candidate, remaining = region_view(
        read_molfile(candidate_molfile),
        proof["variable_atom_indices"],
        proof.get("candidate_hydrogen_anchor"),
    )
    ref, alt = graph(reference), graph(candidate)
    anchors = dict(proof["attachment_mapping"])
    mappings = []
    for mapping in fixed_mappings(ref, alt, selected):
        if (
            frozenset(range(candidate.GetNumAtoms())) - frozenset(mapping.values())
            != remaining
        ):
            continue
        if any(mapping.get(source) != target for source, target in anchors.items()):
            continue
        ports = attachment_mapping(reference, candidate, selected, remaining, mapping)
        if ports is not None and preserved(ref, alt, mapping, ports):
            mappings.append(tuple(sorted(mapping.items())))
    if not mappings:
        raise SARInputError("drawing_alignment_proof")
    # Harmless fixed symmetries do not become new scientific identity claims.
    mapping = min(mappings)
    with rdBase.BlockLogs():
        depict(reference)
        constrained = Chem.Mol(candidate)
        params: Any = rdDepictor.ConstrainedDepictionParams()
        params.acceptFailure = False
        params.alignOnly = False
        params.forceRDKit = True
        params.adjustMolBlockWedging = True
        params.useRingTemplates = False
        try:
            rdDepictor.GenerateDepictionMatching2DStructure(
                constrained, reference, list(mapping), -1, params
            )
        except (ValueError, RuntimeError):
            # A native depiction failure is explicit. Never promote an
            # unconstrained image as aligned, or change the accepted comparison.
            depict(candidate)
            aligned = False
        else:
            if chemical_identity(constrained) != chemical_identity(candidate):
                raise SARInputError("drawing_chemical_identity_changed")
            first, second = reference.GetConformer(), constrained.GetConformer()
            if any(
                (first.GetAtomPosition(a) - second.GetAtomPosition(b)).Length() > 1e-6
                for a, b in mapping
            ):
                raise SARInputError("drawing_alignment_coordinates")
            candidate, aligned = constrained, True
    return PreviewLayout(
        reference,
        candidate,
        tuple(sorted(selected)),
        tuple(sorted(remaining)),
        mapping,
        len(mappings),
        aligned,
    )
