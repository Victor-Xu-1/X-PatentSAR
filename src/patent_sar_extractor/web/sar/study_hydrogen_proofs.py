"""Revalidate new hydrogen mappings with the same native strict matcher."""

from ...core.sar.matching import compile_reference
from ..errors import WebError


def verify_hydrogen_proofs(pairs, plans, by_id, check):
    references = {}
    for pair in pairs:
        region = plans[pair.region_id]["region"]
        if pair.match_status != "matched" or (
            region.get("hydrogen_anchor") is None
            and pair.candidate_hydrogen_anchor is None
        ):
            continue
        check()
        if pair.region_id not in references:
            references[pair.region_id] = compile_reference(
                by_id[region["molecule_id"]].molfile,
                region["atom_indices"],
                hydrogen_anchor=region.get("hydrogen_anchor"),
            )
        proof = references[pair.region_id].compare_details(
            by_id[pair.molecule_id].molfile
        )
        if (
            proof["match_status"] != "matched"
            or proof["variable_atom_indices"] != pair.variable_atom_indices
            or proof["attachment_mapping"] != pair.attachment_mapping
            or proof.get("candidate_hydrogen_anchor") != pair.candidate_hydrogen_anchor
        ):
            raise WebError(
                502,
                "sar_result_invalid",
                "Hydrogen mapping differs from its source-bound strict graph proof.",
            )
