"""Presentation-only coordinates from the existing complete fixed-graph proof.

No MCS, substructure-first match, atom renumbering or scientific result is used.
Equivalent fixed automorphisms are exhausted, then source-index order chooses a
layout only; this does not claim a unique chemical atom correspondence.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from rdkit import Chem, rdBase
from rdkit.Chem import rdDepictor

from ...core.sar.errors import SARInputError
from ...core.sar.graphs import fixed_mappings, graph
from ...core.sar.hydrogen import region_view
from ...core.sar.molecules import chemical_identity, depict, read_molfile
from ...core.sar.regions import attachment_mapping
from ...core.sar.stereo import preserved
from .models import Region
from .preview_geometry import crowded_chain


@dataclass(frozen=True, slots=True)
class PreviewLayout:
    reference: Chem.Mol
    candidate: Chem.Mol
    reference_atoms: tuple[int, ...]
    candidate_atoms: tuple[int, ...]
    mapping: tuple[tuple[int, int], ...]
    alignment_mapping: tuple[tuple[int, int], ...]
    equivalent_mappings: int
    layout: Literal["fixed_background", "fixed_component", "independent"]
    reason: Literal["depiction_failed", "layout_clash"] | None

    @property
    def aligned(self) -> bool:
        return self.layout != "independent"


def alignment_atoms(reference, selected):
    """Choose a complete connected fixed block, not a forced linker end distance.

    The whole complementary chemical graph still passes the retained proof.
    Disconnected fixed fragments may translate as linker length changes; their
    relative drawing distance is not a chemical identity constraint.
    """
    unvisited = set(range(reference.mol.GetNumAtoms())) - set(selected)
    blocks = []
    while unvisited:
        pending, block = [min(unvisited)], set()
        while pending:
            node = pending.pop()
            if node not in unvisited:
                continue
            unvisited.remove(node)
            block.add(node)
            pending.extend(set(reference.adjacency[node]) & unvisited)
        blocks.append(frozenset(block))
    return max(blocks, key=lambda block: (len(block), -min(block))), len(blocks)


def prepare_layout(
    reference_molfile: str,
    candidate_molfile: str,
    region: Region,
    proof: Mapping[str, Any],
    reference_coordinates: Sequence[tuple[float, float]] | None = None,
) -> PreviewLayout:
    """Called only after immutable member/fragment/published-proof verification."""
    if proof.get("match_status") != "matched":
        raise SARInputError("drawing_alignment_proof")
    original_reference = read_molfile(reference_molfile)
    reference, selected = region_view(
        original_reference, region.atom_indices, region.hydrogen_anchor
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
    block, block_count = alignment_atoms(ref, selected)
    alignment_mapping = tuple((a, b) for a, b in mapping if a in block)
    with rdBase.BlockLogs():
        reason = None
        if reference_coordinates is None:
            depict(reference)
        else:
            reference_geometry(original_reference, reference, reference_coordinates)
        constrained = Chem.Mol(candidate)
        params: Any = rdDepictor.ConstrainedDepictionParams()
        params.acceptFailure = False
        params.alignOnly = False
        params.forceRDKit = True
        params.adjustMolBlockWedging = True
        params.useRingTemplates = False
        try:
            rdDepictor.GenerateDepictionMatching2DStructure(
                constrained, reference, list(alignment_mapping), -1, params
            )
        except (ValueError, RuntimeError):
            # A native depiction failure is explicit. Never promote an
            # unconstrained image as aligned, or change the accepted comparison.
            depict(candidate)
            layout = "independent"
            reason = "depiction_failed"
        else:
            if chemical_identity(constrained) != chemical_identity(candidate):
                raise SARInputError("drawing_chemical_identity_changed")
            first, second = reference.GetConformer(), constrained.GetConformer()
            if any(
                (first.GetAtomPosition(a) - second.GetAtomPosition(b)).Length() > 1e-6
                for a, b in alignment_mapping
            ):
                raise SARInputError("drawing_alignment_coordinates")
            if crowded_chain(constrained, remaining):
                depict(candidate)
                layout, reason = "independent", "layout_clash"
            else:
                candidate = constrained
                layout = "fixed_background" if block_count == 1 else "fixed_component"
    return PreviewLayout(
        reference,
        candidate,
        tuple(sorted(selected)),
        tuple(sorted(remaining)),
        mapping,
        alignment_mapping,
        len(mappings),
        layout,
        reason,
    )


def reference_geometry(original, view, coordinates):
    """Original atom order stays the camera anchor, including private H views."""
    if len(coordinates) != original.GetNumAtoms() or any(
        not math.isfinite(value) or abs(value) > 1e6
        for point in coordinates
        for value in point
    ):
        raise SARInputError("drawing_reference_coordinates")
    conformer = Chem.Conformer(original.GetNumAtoms())
    conformer.Set3D(False)
    for index, (x, y) in enumerate(coordinates):
        conformer.SetAtomPosition(index, (x, y, 0))
    original.RemoveAllConformers()
    original.AddConformer(conformer)
    if view.GetNumAtoms() == original.GetNumAtoms():
        view.RemoveAllConformers()
        view.AddConformer(Chem.Conformer(conformer))
    else:
        # region_view adds only one private ordinary H; its placement must not
        # rotate/re-layout the source atoms shared by other matrix directions.
        params: Any = rdDepictor.ConstrainedDepictionParams()
        params.acceptFailure = False
        params.forceRDKit = True
        params.useRingTemplates = False
        params.adjustMolBlockWedging = True
        rdDepictor.GenerateDepictionMatching2DStructure(
            view, original, [(i, i) for i in range(original.GetNumAtoms())], -1, params
        )
    placed = view.GetConformer()
    if any(
        abs(placed.GetAtomPosition(i).x - x) > 1e-6
        or abs(placed.GetAtomPosition(i).y - y) > 1e-6
        for i, (x, y) in enumerate(coordinates)
    ):
        raise SARInputError("drawing_reference_coordinates")
