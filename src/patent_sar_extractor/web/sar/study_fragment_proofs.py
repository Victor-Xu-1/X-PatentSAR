"""Parent validation of partial-aromatic graphic identities from original graphs."""

from functools import lru_cache

from ...core.sar.matching import compile_reference
from ...core.sar.prepared_graphs import GraphPool
from ...core.sar.study_graphs import cut_identity, reference_cut


def verify_aromatic_fragments(report, pairs, by_id, check):
    pool = GraphPool()

    @lru_cache(maxsize=256)
    def source_mol(identifier):
        return pool.read(by_id[identifier].molfile).mol

    grouped = {}
    for pair in pairs:
        grouped.setdefault(pair.region_id, []).append(pair)
    for summary in report.regions:
        region = summary.region
        if not region.atom_indices:
            continue
        selected = set(region.atom_indices)
        mol = source_mol(region.molecule_id)
        aromatic = any(
            bond.GetIsAromatic()
            and (
                (bond.GetBeginAtomIdx() in selected)
                != (bond.GetEndAtomIdx() in selected)
            )
            for bond in mol.GetBonds()
        )
        if not aromatic:
            if any(
                fragment.representation == "aromatic_graph"
                for fragment in summary.fragments
            ):
                raise ValueError("study_fragment_graph_proof")
            continue
        check()
        reference = by_id[region.molecule_id].molfile
        expected = reference_cut(reference, region.atom_indices, pool=pool)
        if (
            expected["fixed_background_sha256"] != summary.fixed_background_sha256
            or expected["id"] != summary.reference_fragment_id
        ):
            raise ValueError("study_fragment_graph_proof")
        fragments = {fragment.id: fragment for fragment in summary.fragments}
        matcher = compile_reference(reference, region.atom_indices, pool=pool)
        identities = {expected["id"]: expected}
        for pair in grouped.get(region.id, ()):
            if pair.match_status != "matched":
                continue
            check()
            candidate = by_id[pair.molecule_id].molfile
            proof = matcher.compare_details(candidate)
            if (
                proof["match_status"] != "matched"
                or proof["variable_atom_indices"] != pair.variable_atom_indices
                or proof["attachment_mapping"] != pair.attachment_mapping
                or pair.candidate_hydrogen_anchor is not None
            ):
                raise ValueError("study_fragment_graph_proof")
            fragment = cut_identity(
                candidate,
                proof["variable_atom_indices"],
                proof["attachment_mapping"],
                pool=pool,
            )
            if (
                fragment["id"] != pair.fragment_id
                or fragment["fixed_background_sha256"]
                != expected["fixed_background_sha256"]
            ):
                raise ValueError("study_fragment_graph_proof")
            identities[fragment["id"]] = fragment
        if set(identities) != set(fragments):
            raise ValueError("study_fragment_graph_proof")
        for identifier, identity in identities.items():
            actual = fragments[identifier]
            if (
                actual.is_reference != (identifier == expected["id"])
                or actual.smiles is not None
                or actual.representation != "aromatic_graph"
                or actual.graph_smiles != identity["graph_smiles"]
            ):
                raise ValueError("study_fragment_graph_proof")
