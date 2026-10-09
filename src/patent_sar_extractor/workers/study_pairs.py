"""One compiled strict matcher per region, with native proof-bound pair chunks."""

from __future__ import annotations

from patent_sar_extractor.core.sar.errors import SARInputError
from patent_sar_extractor.core.sar.matching import compile_reference
from patent_sar_extractor.core.sar.statistics import compare_observations
from patent_sar_extractor.core.sar.study_graphs import cut_identity, reference_cut
from patent_sar_extractor.core.sar.study_summaries import region_summary
from patent_sar_extractor.web.sar.models import Pair

from .study_checkpoints import BATCH_SIZE, load, progress, save


def make_pair(
    reference,
    candidate,
    region,
    policy,
    observations,
    confirmed,
    matcher,
    reference_fragment,
):
    proof = {
        "match_status": "ineligible",
        "reasons": ["source_structure_ineligible"],
        "variable_atom_indices": [],
        "attachment_mapping": [],
    }
    if candidate["eligible"] and candidate.get("molfile"):
        proof = matcher.compare_details(candidate["molfile"])
    left, right = observations[reference["id"]], observations[candidate["id"]]
    measured = {
        "comparison": "indeterminate",
        "reference_values": [item["value"] for item in left],
        "candidate_values": [item["value"] for item in right],
        "fold_change": None,
        "evidence_basis": "insufficient",
        "reasons": [],
    }
    fragment = None
    if proof["match_status"] == "matched":
        fragment = cut_identity(
            candidate["molfile"],
            proof["variable_atom_indices"],
            proof["attachment_mapping"],
        )
        if (
            fragment["fixed_background_sha256"]
            != reference_fragment["fixed_background_sha256"]
        ):
            raise SARInputError("study_fixed_background_identity")
        metric = (left or right)[0]["metric_id"] if left or right else "missing"
        measured = compare_observations(
            left, right, metric, policy["direction"], policy["grade_order"], confirmed
        )
        if any(item.get("_sar_declared_context") for item in [*left, *right]):
            measured["reasons"].append(
                "operator_declared_context_not_automatic_verification"
            )
            if measured["evidence_basis"] == "recorded_context":
                measured["evidence_basis"] = "source_declared"
        # The scalar comparator may refuse its own per-comparison budget; study
        # evidence still retains all selected raw observations without truncation.
        measured.update(
            reference_values=[item["value"] for item in left],
            candidate_values=[item["value"] for item in right],
        )
    pair = Pair(
        reference_id=reference["id"],
        molecule_id=candidate["id"],
        label=candidate["label"],
        region_id=region["id"],
        fragment_id=fragment["id"] if fragment else None,
        match_status=proof["match_status"],
        variable_atom_indices=proof["variable_atom_indices"],
        attachment_mapping=proof["attachment_mapping"],
        reasons=sorted({*proof["reasons"], *measured.pop("reasons")}),
        **measured,
    )
    return pair.model_dump(), fragment


def analyse_pairs(
    safe,
    identity,
    rows,
    regions,
    request,
    observations,
    assessments,
    check,
    *,
    prepared=None,
):
    indexed = {row["id"]: row for row in rows}
    policy = request["policies"][0]
    summaries, batch = [], []
    chunk_index = completed = matched = 0
    saved = None
    total = len(regions) * (len(rows) - 1)

    def flush():
        nonlocal chunk_index, completed, matched
        if not batch:
            return
        check()
        start = chunk_index * BATCH_SIZE
        name = f"chunk-{chunk_index:04d}.json"
        if saved is None:
            save(safe.root, name, identity, start, "pairs", batch)
        completed += len(batch)
        matched += sum(pair["match_status"] == "matched" for pair in batch)
        progress(safe.root, identity, len(rows) + completed, matched)
        chunk_index += 1
        batch.clear()

    for region in regions:
        check()
        reference = indexed[region["molecule_id"]]
        matcher = compile_reference(reference["molfile"], region["atom_indices"])
        ref_fragment = reference_cut(reference["molfile"], region["atom_indices"])
        fragments = {ref_fragment["id"]: ref_fragment}
        compact = []
        for candidate in rows:
            if candidate["id"] == reference["id"]:
                continue
            check()
            if not batch:
                saved = load(
                    safe,
                    f"chunk-{chunk_index:04d}.json",
                    identity,
                    chunk_index * BATCH_SIZE,
                    "pairs",
                )
                if saved is not None and len(saved) != min(
                    BATCH_SIZE, total - completed
                ):
                    raise SARInputError("study_pair_checkpoint_coverage")
            if saved is None:
                pair, fragment = make_pair(
                    reference,
                    candidate,
                    region,
                    policy,
                    observations,
                    request["confirm_context"],
                    matcher,
                    ref_fragment,
                )
            else:
                pair = Pair.model_validate(saved[len(batch)]).model_dump()
                if (
                    pair["reference_id"] != reference["id"]
                    or pair["molecule_id"] != candidate["id"]
                    or pair["region_id"] != region["id"]
                    or pair["label"] != candidate["label"]
                    or pair["reference_values"]
                    != [item["value"] for item in observations[reference["id"]]]
                    or pair["candidate_values"]
                    != [item["value"] for item in observations[candidate["id"]]]
                ):
                    raise SARInputError("study_pair_checkpoint_coverage")
                fragment = None
                if pair["match_status"] == "matched":
                    if not candidate["eligible"]:
                        raise SARInputError("study_pair_checkpoint_proof")
                    fragment = cut_identity(
                        candidate["molfile"],
                        pair["variable_atom_indices"],
                        pair["attachment_mapping"],
                    )
                    if (
                        fragment["id"] != pair["fragment_id"]
                        or fragment["fixed_background_sha256"]
                        != ref_fragment["fixed_background_sha256"]
                    ):
                        raise SARInputError("study_pair_checkpoint_proof")
                elif (
                    pair["variable_atom_indices"]
                    or pair["attachment_mapping"]
                    or pair["fragment_id"] is not None
                ):
                    raise SARInputError("study_pair_checkpoint_proof")
            if fragment:
                fragments[fragment["id"]] = fragment
            compact.append(
                {
                    key: pair[key]
                    for key in (
                        "molecule_id",
                        "match_status",
                        "fragment_id",
                        "comparison",
                    )
                }
            )
            batch.append(pair)
            if len(batch) == BATCH_SIZE:
                flush()
        summaries.append(
            region_summary(
                region,
                reference,
                ref_fragment,
                compact,
                fragments,
                observations,
                policy,
                assessments,
                prepared=prepared,
            )
        )
    flush()
    if completed != len(regions) * (len(rows) - 1):
        raise SARInputError("study_pair_completeness")
    return summaries, chunk_index, matched
