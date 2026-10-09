"""Exact-context activities and transparent bounded candidate prioritization."""

from __future__ import annotations

from patent_sar_extractor.core.sar.study_conditions import declared_observation
from patent_sar_extractor.core.sar.study_contexts import context_identity
from patent_sar_extractor.core.sar.study_priority import (
    pareto_fronts,
    select_candidates,
)
from patent_sar_extractor.core.sar.study_statistics import assess
from patent_sar_extractor.web.errors import WebError
from patent_sar_extractor.web.lead_chemistry import chemical_features, similarity

from .study_evidence import secondary_evidence


def collect_activities(rows, policies, confirmed, declarations=()):
    declared = {item["context_id"]: item for item in declarations}
    observations = {
        policy["context_id"]: {row["id"]: [] for row in rows} for policy in policies
    }
    for row in rows:
        for observation in row["observations"]:
            identifier = context_identity(observation)
            if identifier in observations:
                observations[identifier][row["id"]].append(
                    declared_observation(observation, declared.get(identifier))
                )
    assessments = {
        policy["context_id"]: {
            row["id"]: assess(
                observations[policy["context_id"]][row["id"]], policy, confirmed
            )
            for row in rows
        }
        for policy in policies
    }
    for policy in policies:
        identifier = policy["context_id"]
        if identifier in declared:
            for state in assessments[identifier].values():
                if state["evidence_basis"] == "recorded_context":
                    state["evidence_basis"] = "source_declared"
                state["reasons"].append(
                    "operator_declared_context_not_automatic_verification"
                )
    return observations, assessments


def rank_candidates(rows, descriptors, request, observations, assessments, check):
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
            state["value"] is not None
            and state["evidence_basis"] in {"recorded_context", "source_declared"}
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
                "activity_bands": {
                    policy["context_id"]: state.get("band", "unclassified")
                    for policy, state in zip(policies, states, strict=True)
                },
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
