"""Validate one immutable study packet against the shared DTO/identity authorities."""

from __future__ import annotations

import hashlib
import re
from importlib.metadata import version

from patent_sar_extractor.core.identifier_order import natural_identifier_key
from patent_sar_extractor.core.sar.errors import SARInputError
from patent_sar_extractor.core.sar.study_conditions import validate_declarations
from patent_sar_extractor.core.sar.study_contexts import context_catalog
from patent_sar_extractor.core.sar.values import grade_ranks
from patent_sar_extractor.web.prediction_models import METRIC_KEYS
from patent_sar_extractor.web.sar.assets import digest
from patent_sar_extractor.web.sar.engine import engine_identity
from patent_sar_extractor.web.sar.models import Dataset, Molecule, Region
from patent_sar_extractor.web.sar.study_models import StudyRequest

MAX_COMPARISONS = 75000
MAX_ROWS = 25000
MAX_OBSERVATIONS = 100000


def read_input(safe, input_sha256):
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
    validate_declarations(
        dataset,
        contexts,
        known.intersection(policy["context_id"] for policy in request["policies"]),
        request["context_declarations"],
    )
    return dataset, rows, regions, cores, request, contexts, packet["engine_sha256"]
