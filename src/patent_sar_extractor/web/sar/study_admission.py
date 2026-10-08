"""Validate full-study parameters before entering the existing SAR queue."""

from __future__ import annotations

from ...core.sar.study_contexts import context_catalog
from ...core.sar.values import grade_ranks
from ..errors import WebError
from .admission import existing, publish
from .study_models import StudyProfile, StudyRequest


def profile(service, dataset_id: str) -> StudyProfile:
    dataset = service.dataset(dataset_id)
    molecules = service.datasets.all(dataset_id)
    try:
        contexts = context_catalog(
            [row.model_dump() for row in molecules],
            [metric.model_dump() for metric in dataset.metrics],
        )
    except ValueError as error:
        raise WebError(
            422,
            "sar_study_context",
            "Recorded contexts exceed their complete-catalog bound.",
        ) from error
    return StudyProfile(
        dataset_id=dataset.id,
        dataset_revision=dataset.revision,
        contexts=contexts,
        regions=service.datasets.regions(dataset_id),
    )


def enqueue_study(queue, dataset_id: str, request: StudyRequest):
    old, request_hash = existing(queue, dataset_id, request)
    if old:
        return old
    dataset = queue.service.current(dataset_id, request.expected_dataset_revision)
    molecules = queue.service.datasets.all(dataset_id)
    if not molecules:
        raise WebError(422, "sar_pool_small", "A study requires source records.")
    try:
        contexts = context_catalog(
            [row.model_dump() for row in molecules],
            [metric.model_dump() for metric in dataset.metrics],
        )
        for policy in request.policies:
            grade_ranks(policy.grade_order)
            if policy.grade_order and policy.strong_threshold is not None:
                raise ValueError("mixed strong definition")
    except ValueError as error:
        raise WebError(
            422,
            "sar_study_policy",
            "Use distinct grades or a numeric threshold, never both.",
        ) from error
    known = {context["id"]: context for context in contexts}
    ids = [policy.context_id for policy in request.policies]
    if len(set(ids)) != len(ids) or not set(ids).issubset(known):
        raise WebError(
            422,
            "sar_study_context",
            "Select distinct exact contexts from this dataset.",
        )
    if len(set(request.region_ids)) != len(request.region_ids):
        raise WebError(422, "sar_study_region", "Study regions must be distinct.")
    regions = [
        queue.service.datasets.region(identifier, dataset_id)
        for identifier in request.region_ids
    ]
    cores = [
        queue.service.datasets.region(identifier, dataset_id)
        for identifier in request.core_ids
    ]
    if (
        len(set(request.core_ids)) != len(request.core_ids)
        or any(region.kind != "variable" for region in regions)
        or any(core.kind != "core" for core in cores)
    ):
        raise WebError(
            422,
            "sar_study_region",
            "Core and variable-region roles must be explicit and distinct.",
        )
    if any(
        region.dataset_revision != dataset.revision for region in [*regions, *cores]
    ):
        raise WebError(
            409,
            "sar_graph_changed",
            "A saved region is from a different source revision.",
        )
    if len(regions) * (len(molecules) - 1) > 75000:
        raise WebError(
            413,
            "sar_study_limit",
            "Study exceeds 75000 strict comparisons; choose fewer regions. No data was truncated.",
        )
    return publish(
        queue,
        dataset,
        molecules,
        request,
        request_hash,
        regions=regions,
        kind="study",
        metric_id=known[ids[0]]["metric_id"],
        cores=cores,
    )
