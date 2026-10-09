"""Thin orchestration for one bounded complete immutable SAR study report."""

from __future__ import annotations

import time
from pathlib import Path

from patent_sar_extractor.core.sar.errors import SARInputError
from patent_sar_extractor.core.sar.study_cores import confirmed_core_summaries
from patent_sar_extractor.core.sar.study_distributions import DistributionContext
from patent_sar_extractor.core.sar.study_statistics import distribution
from patent_sar_extractor.core.sar.study_summaries import scaffold_summaries
from patent_sar_extractor.web.files import SafeFiles
from patent_sar_extractor.web.sar.assets import atomic_json, digest
from patent_sar_extractor.web.sar.study_models import StudyReport

from .study_candidates import collect_activities, rank_candidates
from .study_checkpoints import progress
from .study_descriptors import descriptor_batches
from .study_inputs import read_input
from .study_pairs import analyse_pairs
from .study_strength import resolve_strength

DEADLINE_SECONDS = 175


def analyse_study(root: Path, input_sha256: str) -> dict:
    started = time.monotonic()

    def check():
        if time.monotonic() - started >= DEADLINE_SECONDS:
            raise TimeoutError("study_deadline_exceeded")

    safe = SafeFiles(root)
    dataset, rows, regions, cores, request, contexts, engine = read_input(
        safe, input_sha256
    )
    identity = {"input_sha256": input_sha256, "engine_sha256": engine}
    check()
    descriptors = descriptor_batches(safe, identity, rows, check)
    observations, assessments = collect_activities(
        rows,
        request["policies"],
        request["confirm_context"],
        request["context_declarations"],
    )
    request = {
        **request,
        "policies": resolve_strength(
            request["policies"], contexts, observations, assessments
        ),
    }
    domains = {
        policy["context_id"]: DistributionContext(
            observations[policy["context_id"]],
            policy,
            assessments[policy["context_id"]],
        )
        for policy in request["policies"]
    }
    primary = request["policies"][0]
    primary_obs, primary_states = (
        observations[primary["context_id"]],
        assessments[primary["context_id"]],
    )
    summaries, chunks, matched = analyse_pairs(
        safe,
        identity,
        rows,
        regions,
        request,
        primary_obs,
        primary_states,
        check,
        prepared=domains[primary["context_id"]],
    )
    report_rows, candidates = rank_candidates(
        rows, descriptors, request, observations, assessments, check
    )
    core_groups, core_warnings = confirmed_core_summaries(
        cores,
        rows,
        primary_obs,
        primary,
        primary_states,
        check,
        prepared=domains[primary["context_id"]],
    )
    warnings = {
        "research_only_scientific_validation_required",
        "article_author_algorithm_not_reproduced",
        "murcko_scaffolds_descriptive_not_matching_proof",
        "region_scaffold_bins_use_primary_policy",
        "row_strong_flag_uses_primary_policy",
        "physchem_prediction_secondary_evidence_not_acceptance",
        "membership_counts_are_source_ids_not_independent_graphs",
        "region_selections_not_independent_replications",
    }
    warnings.update(reason for row in report_rows for reason in row["reasons"])
    warnings.update(core_warnings)
    if any(row["scaffold_id"] is None for row in descriptors):
        warnings.add("scaffold_unavailable_rows_retained")
    if cores:
        warnings.add("confirmed_cores_descriptive_not_strict_background")
    if len(candidates) < 5:
        warnings.add("fewer_than_five_independent_rankable_graphs")
    distributions = [
        distribution(
            [row["id"] for row in rows],
            observations[policy["context_id"]],
            policy,
            assessments[policy["context_id"]],
            prepared=domains[policy["context_id"]],
        )
        for policy in request["policies"]
    ]
    if any(item["missing_molecules"] for item in distributions):
        warnings.add("activity_absence_retained_in_report")
    if any(item["unresolved_molecules"] for item in distributions):
        warnings.add("activity_unresolved_retained_in_report")
    check()
    report = StudyReport(
        dataset_id=dataset["id"],
        dataset_revision=dataset["revision"],
        title=request["title"],
        counting_contract="unique-molecules-v2",
        source_acceptance=dataset["source_acceptance"],
        context_declarations=request["context_declarations"],
        **identity,
        molecule_count=len(rows),
        eligible_count=sum(row["eligible"] for row in report_rows),
        observation_count=sum(len(row["observations"]) for row in rows),
        strict_pair_count=len(regions) * (len(rows) - 1),
        matched_pair_count=matched,
        comparable_pair_count=sum(summary["comparable"] for summary in summaries),
        contexts=contexts,
        policies=request["policies"],
        distributions=distributions,
        scaffolds=[
            *scaffold_summaries(
                descriptors,
                primary_obs,
                primary,
                primary_states,
                prepared=domains[primary["context_id"]],
            ),
            *core_groups,
        ],
        regions=summaries,
        candidates=candidates,
        rows=report_rows,
        warnings=sorted(warnings),
    ).model_dump()
    existing = safe.json("report.json")
    if existing is not None and existing != report:
        raise SARInputError("study_report_checkpoint_identity")
    if existing is None:
        atomic_json(root, "report.json", report)
    progress(root, identity, len(rows) + len(regions) * (len(rows) - 1), matched)
    return {**identity, "chunks": chunks, "report_sha256": digest(report)}
