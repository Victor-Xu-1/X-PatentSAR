"""Canonical boundary indexes propose candidates; strict matching remains proof."""

from rdkit import Chem, rdBase

from .cut_topology import boundary_regions


def candidate_cuts(mol, inspect, excluded, *, max_variable, max_fraction, min_fixed):
    count = mol.GetNumAtoms()
    previous, fragmented = None, None
    for boundary, mask in boundary_regions(mol, inspect):
        size = mask.bit_count()
        if (
            not size
            or size > max_variable
            or size > count * max_fraction
            or count - size < min_fixed
        ):
            continue
        selected = tuple(index for index in range(count) if mask & (1 << index))
        with rdBase.BlockLogs():
            if previous != boundary:
                fragmented = Chem.FragmentOnBonds(
                    mol, list(boundary), dummyLabels=[(0, 0)] * len(boundary)
                )
                for atom in list(fragmented.GetAtoms())[count:]:
                    atom.SetAtomMapNum(1)
                previous = boundary
            included = set(selected)
            for atom in list(fragmented.GetAtoms())[count:]:
                if any(
                    neighbor.GetIdx() in included for neighbor in atom.GetNeighbors()
                ):
                    included.add(atom.GetIdx())
            fixed = sorted(set(range(fragmented.GetNumAtoms())) - included)
            fragment = Chem.MolFragmentToSmiles(
                fragmented, atomsToUse=fixed, canonical=True, isomericSmiles=True
            )
            core = Chem.MolFromSmiles(fragment)
            if core is None:
                excluded["unsupported_index_fragment"] += 1
                continue
            key = Chem.MolToSmiles(core, canonical=True, isomericSmiles=True)
        yield key, selected, len(boundary)
