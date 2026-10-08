"""Bounded complete multi-region SAR reports from immutable schema2 packets."""

from __future__ import annotations

import hashlib
import re
import time
from importlib.metadata import version
from pathlib import Path

from patent_sar_extractor.core.identifier_order import natural_identifier_key
from patent_sar_extractor.core.sar.errors import SARInputError
from patent_sar_extractor.core.sar.study_contexts import (
    context_catalog,
    context_identity,
)
from patent_sar_extractor.core.sar.study_cores import confirmed_core_summaries
from patent_sar_extractor.core.sar.study_priority import (
    pareto_fronts,
    select_candidates,
)
from patent_sar_extractor.core.sar.study_statistics import assess, distribution
from patent_sar_extractor.core.sar.study_summaries import scaffold_summaries
from patent_sar_extractor.core.sar.values import grade_ranks
from patent_sar_extractor.web.errors import WebError
from patent_sar_extractor.web.files import SafeFiles
from patent_sar_extractor.web.lead_chemistry import chemical_features, similarity
from patent_sar_extractor.web.prediction_models import METRIC_KEYS
from patent_sar_extractor.web.sar.assets import atomic_json, digest
from patent_sar_extractor.web.sar.engine import engine_identity
from patent_sar_extractor.web.sar.models import Dataset, Molecule, Region
from patent_sar_extractor.web.sar.study_models import StudyReport, StudyRequest

from .study_checkpoints import BATCH_SIZE, load, progress, save
from .study_descriptors import describe
from .study_evidence import secondary_evidence
from .study_pairs import analyse_pairs

MAX_COMPARISONS = 75000
MAX_ROWS = 25000
MAX_OBSERVATIONS = 100000
DEADLINE_SECONDS = 175


def _input(safe, input_sha256):
    packet = safe.json("input.json", optional=False)
    if (
        not isinstance(packet, dict)
        or set(packet) - {"producer"}
        != {
            "schema",
            "dataset",
            "molecules",
            "regions",
            "cores",
            "request",
            "job_id",
            "engine_sha256",
        }
        or packet["schema"] != 2
        or digest(packet) != input_sha256
        or packet["engine_sha256"] != engine_identity()
        or packet["job_id"] != safe.root.name
    ):
        raise SARInputError("study_input_identity")
    if "producer" in packet and (
        not isinstance(packet["producer"], dict)
        or set(packet["producer"]) != {"product", "rdkit_version"}
        or packet["producer"]["rdkit_version"] != version("rdkit")
    ):
        raise SARInputError("study_producer_identity")
    dataset = Dataset.model_validate(packet["dataset"]).model_dump()
    request = StudyRequest.model_validate(packet["request"]).model_dump()
    rows = [Molecule.model_validate(row).model_dump() for row in packet["molecules"]]
    regions = [
        Region.model_validate(region).model_dump() for region in packet["regions"]
    ]
    cores = [Region.model_validate(core).model_dump() for core in packet["cores"]]
    if (
        not 1 <= len(rows) <= MAX_ROWS
        or len({row["id"] for row in rows}) != len(rows)
        or len(regions) * (len(rows) - 1) > MAX_COMPARISONS
        or len({region["id"] for region in regions}) != len(regions)
        or [region["id"] for region in regions] != request["region_ids"]
        or [core["id"] for core in cores] != request["core_ids"]
        or len({core["id"] for core in cores}) != len(cores)
        or set(request["region_ids"]) & set(request["core_ids"])
        or any(region["kind"] != "variable" for region in regions)
        or any(core["kind"] != "core" for core in cores)
        or dataset["row_count"] != len(rows)
        or dataset["revision"] != request["expected_dataset_revision"]
        or dataset["stale"]
        or sum(len(row["observations"]) for row in rows) > MAX_OBSERVATIONS
        or len({policy["context_id"] for policy in request["policies"]})
        != len(request["policies"])
    ):
        raise SARInputError("study_input_completeness")
    for policy in request["policies"]:
        grade_ranks(policy["grade_order"])
        if policy["grade_order"] and policy["strong_threshold"] is not None:
            raise SARInputError("study_policy_strength_conflict")
    indexed = {row["id"]: row for row in rows}
    for row in rows:
        if (
            set(row["properties"]) - set(METRIC_KEYS)
            or set(row["property_origins"]) - set(METRIC_KEYS)
            or any(
                not re.fullmatch(r"[a-z][a-z0-9_]{0,99}", code)
                for code in row["issues"]
            )
            or any(
                origin == "manual_null" and row["properties"].get(key) is not None
                for key, origin in row["property_origins"].items()
            )
        ):
            raise SARInputError("study_source_metadata")
        if row["eligible"] and (
            not row["molfile"]
            or hashlib.sha256(row["molfile"].encode()).hexdigest()
            != row["graph_sha256"]
        ):
            raise SARInputError("study_graph_identity")
    for region in [*regions, *cores]:
        reference = indexed.get(region["molecule_id"])
        if (
            reference is None
            or not reference["eligible"]
            or region["dataset_id"] != dataset["id"]
            or region["dataset_revision"] != dataset["revision"]
            or region["graph_sha256"] != reference["graph_sha256"]
        ):
            raise SARInputError("study_region_identity")
    rows.sort(
        key=lambda row: (
            natural_identifier_key(row["label"]),
            natural_identifier_key(row["id"]),
        )
    )
    contexts = context_catalog(rows, dataset["metrics"])
    known = {context["id"] for context in contexts}
    if any(policy["context_id"] not in known for policy in request["policies"]):
        raise SARInputError("study_context_identity")
    return dataset, rows, regions, cores, request, contexts, packet["engine_sha256"]


def _descriptors(safe, identity, rows, check):
    output = []
    for start in range(0, len(rows), BATCH_SIZE):
        check()
        batch = rows[start : start + BATCH_SIZE]
        name = f"descriptors-{start // BATCH_SIZE:04d}.json"
        records = load(safe, name, identity, start, "rows")
        if records is None:
            records = []
            for molecule in batch:
                check()
                records.append(describe(molecule))
            save(safe.root, name, identity, start, "rows", records)
        elif len(records) != len(batch) or any(
            record.get("molecule_id") != row["id"]
            or record.get("source_graph_sha256") != row["graph_sha256"]
            or record.get("eligible") != row["eligible"]
            or record.get("predictions") != row["predictions"]
            or record.get("prediction_origin") != row["prediction_origin"]
            for record, row in zip(records, batch, strict=True)
        ):
            raise SARInputError("study_descriptor_checkpoint_identity")
        # Typed finite row validation also applies to cached descriptor packets.
        for record in records:
            if set(record) != {
                "molecule_id",
                "source_graph_sha256",
                "eligible",
                "canonical_smiles",
                "scaffold_id",
                "scaffold_smiles",
                "properties",
                "property_origins",
                "predictions",
                "prediction_origin",
                "reasons",
            }:
                raise SARInputError("study_descriptor_checkpoint_shape")
            if (
                not isinstance(record["properties"], dict)
                or set(record["properties"]) != set(METRIC_KEYS)
                or not isinstance(record["property_origins"], dict)
                or set(record["property_origins"]) != set(METRIC_KEYS)
                or not isinstance(record["reasons"], list)
            ):
                raise SARInputError("study_descriptor_checkpoint_shape")
        output.extend(records)
        progress(safe.root, identity, len(output), 0)
    return output


def _activities(rows, policies, confirmed):
    observations = {
        policy["context_id"]: {row["id"]: [] for row in rows} for policy in policies
    }
    for row in rows:
        for observation in row["observations"]:
            identifier = context_identity(observation)
            if identifier in observations:
                observations[identifier][row["id"]].append(observation)
    assessments = {
        policy["context_id"]: {
            row["id"]: assess(
                observations[policy["context_id"]][row["id"]], policy, confirmed
            )
            for row in rows
        }
        for policy in policies
    }
    return observations, assessments


def _ranked_rows(rows, descriptors, request, observations, assessments, check):
    policies = request["policies"]
    output, vectors, features, features_by_graph = [], {}, {}, {}
    primary = policies[0]["context_id"]
    graph_counts = {}
    graph_members = {}
    for descriptor in descriptors:
        if descriptor["canonical_smiles"]:
            graph_counts[descriptor["canonical_smiles"]] = (
                graph_counts.get(descriptor["canonical_smiles"], 0) + 1
            )
            graph_members.setdefault(descriptor["canonical_smiles"], []).append(
                descriptor["molecule_id"]
            )
    conflicting_aliases = set()
    for members in graph_members.values():
        if len(members) < 2:
            continue
        for policy in policies:
            values = {
                assessments[policy["context_id"]][identifier]["value"]
                for identifier in members
            } - {None}
            unresolved = any(
                assessments[policy["context_id"]][identifier]["status"]
                in {"indeterminate", "context_mismatch"}
                for identifier in members
            )
            if len(values) > 1 or unresolved:
                conflicting_aliases.update(members)
    families = [set() for _ in policies]
    for molecule, descriptor in zip(rows, descriptors, strict=True):
        check()
        states = [
            assessments[policy["context_id"]][molecule["id"]] for policy in policies
        ]
        known = [
            state["value"] is not None and state["evidence_basis"] == "recorded_context"
            for state in states
        ]
        reasons = set(descriptor["reasons"])
        if graph_counts.get(descriptor["canonical_smiles"], 0) > 1:
            reasons.add("nonindependent_source_graph")
        reasons.update(reason for state in states for reason in state["reasons"])
        eligible = descriptor["eligible"]
        status = (
            "not_selected" if all(known) else "partial" if any(known) else "unranked"
        )
        if not eligible:
            status = "ineligible"
        elif "stereochemistry_unassigned" in reasons:
            status = "unranked"
        elif molecule["id"] in conflicting_aliases:
            status = "unranked"
            reasons.add("graph_alias_measurements_conflict")
        elif all(known):
            vector = tuple(state["value"] for state in states)
            vectors[molecule["id"]] = vector
            for family, value in zip(families, vector, strict=True):
                family.add("ordinal" if value.kind == "ordinal" else "numeric")
        else:
            reasons.add("priority_requires_complete_recorded_context")
        output.append(
            {
                "molecule_id": molecule["id"],
                "label": molecule["label"],
                "eligible": eligible,
                "scaffold_id": descriptor["scaffold_id"],
                "values": {
                    key: [item["value"] for item in values[molecule["id"]]]
                    for key, values in observations.items()
                },
                "activity_status": {
                    policy["context_id"]: state["status"]
                    for policy, state in zip(policies, states, strict=True)
                },
                "strong": assessments[primary][molecule["id"]]["strong"],
                "properties": descriptor["properties"],
                "property_origins": descriptor["property_origins"],
                "predictions": descriptor["predictions"],
                "prediction_origin": descriptor["prediction_origin"],
                "pareto_front": None,
                "priority_group": None,
                "selection_order": None,
                "candidate_status": status,
                "coverage": sum(known) / len(policies),
                "reasons": sorted(reasons | {"study_priority_not_validated_lead"}),
            }
        )
    if any(len(family) > 1 for family in families):
        vectors.clear()
        for row in output:
            if row["candidate_status"] == "not_selected":
                row["candidate_status"] = "unranked"
                row["reasons"].append("priority_mixed_measurement_kinds")
    fronts = pareto_fronts(vectors, policies, check)
    for row, descriptor in zip(output, descriptors, strict=True):
        row["pareto_front"] = row["priority_group"] = fronts.get(row["molecule_id"])
        if row["pareto_front"] is not None:
            check()
            try:
                canonical = descriptor["canonical_smiles"]
                if canonical not in features_by_graph:
                    features_by_graph[canonical] = chemical_features(canonical)
                features[row["molecule_id"]] = features_by_graph[canonical]
            except (WebError, ValueError, RuntimeError):
                row["reasons"].append("diversity_out_of_domain")
    evidence = secondary_evidence(output, check)
    candidates = select_candidates(
        output,
        request["candidate_count"],
        features,
        similarity,
        check,
        identities={
            row["molecule_id"]: descriptor["canonical_smiles"]
            for row, descriptor in zip(output, descriptors, strict=True)
        },
        evidence=evidence,
    )
    return output, candidates


def analyse_study(root: Path, input_sha256: str) -> dict:
    started = time.monotonic()

    def check():
        if time.monotonic() - started >= DEADLINE_SECONDS:
            raise TimeoutError("study_deadline_exceeded")

    safe = SafeFiles(root)
    dataset, rows, regions, cores, request, contexts, engine = _input(
        safe, input_sha256
    )
    identity = {"input_sha256": input_sha256, "engine_sha256": engine}
    check()
    descriptors = _descriptors(safe, identity, rows, check)
    observations, assessments = _activities(
        rows, request["policies"], request["confirm_context"]
    )
    primary = request["policies"][0]
    primary_obs, primary_states = (
        observations[primary["context_id"]],
        assessments[primary["context_id"]],
    )
    summaries, chunks, matched = analyse_pairs(
        safe, identity, rows, regions, request, primary_obs, primary_states, check
    )
    report_rows, candidates = _ranked_rows(
        rows, descriptors, request, observations, assessments, check
    )
    core_groups, core_warnings = confirmed_core_summaries(
        cores, rows, primary_obs, primary, primary_states, check
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
            *scaffold_summaries(descriptors, primary_obs, primary, primary_states),
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
