"""One nonce, cleanup and immutable-input admission path for both SAR views."""

from __future__ import annotations

import uuid
from importlib.metadata import version

from ...contracts import product_ref
from ..errors import WebError
from ..storage import encode, now
from .assets import MAX_PACKET_BYTES, atomic_json, digest
from .engine import engine_identity
from .models import SARJob


def existing(queue, dataset_id: str, request) -> tuple[SARJob | None, str]:
    if queue.retained_lease or queue.recovery_blocked:
        raise WebError(
            409,
            "sar_process_unverified",
            "Verify previous SAR worker cleanup before starting another analysis.",
        )
    with queue.service.store.connect() as connection:
        if connection.execute(
            "SELECT 1 FROM jobs WHERE status NOT IN ('queued','running') AND json_extract(payload,'$.started_at') IS NOT NULL AND cleanup_verified=0 LIMIT 1"
        ).fetchone():
            raise WebError(
                409,
                "sar_process_unverified",
                "Previous started SAR attempt has no verified cleanup.",
            )
    request_hash = digest([dataset_id, request.model_dump(exclude={"request_id"})])
    old = queue.jobs.existing(request.request_id, request_hash)
    return (queue.view(old.id) if old else None), request_hash


def publish(
    queue,
    dataset,
    molecules,
    request,
    request_hash,
    *,
    regions,
    kind,
    metric_id,
    cores=(),
):
    identifier, identity = uuid.uuid4().hex, engine_identity()
    packet = {
        "schema": 2 if kind == "study" else 1,
        "job_id": identifier,
        "engine_sha256": identity,
        "producer": {"product": product_ref(), "rdkit_version": version("rdkit")},
        "dataset": dataset.model_dump(),
        "molecules": [item.model_dump() for item in molecules],
        "request": request.model_dump(),
    }
    if kind == "study":
        packet["regions"] = [region.model_dump() for region in regions]
        packet["cores"] = [core.model_dump() for core in cores]
    else:
        packet["region"] = regions[0].model_dump()
    if len(encode(packet).encode()) > MAX_PACKET_BYTES:
        raise WebError(
            413,
            "sar_asset_limit",
            "Complete study input exceeds 32 MiB; no records were truncated.",
        )
    input_hash = digest(packet)
    root = queue.service.assets.area("results") / identifier
    queue.service.current(dataset.id, dataset.revision)
    comparisons = len(regions) * (len(molecules) - 1)
    value = SARJob(
        id=identifier,
        dataset_id=dataset.id,
        region_id=regions[0].id if regions else "",
        metric_id=metric_id,
        kind=kind,
        status="queued",
        total=len(molecules) + comparisons if kind == "study" else comparisons,
        created_at=now(),
        input_sha256=input_hash,
    )
    value = queue.jobs.create(
        value,
        request.request_id,
        request_hash,
        {
            "engine_sha256": identity,
            "producer": packet["producer"],
            "attempt_id": uuid.uuid4().hex,
            "request": request.model_dump(),
            "kind": kind,
        },
        str(root),
    )
    if value.id != identifier:
        return queue.view(value.id)
    try:
        # The admission-selected root remains authoritative after a settings edit.
        root = queue.service.assets.job_files(str(root), identifier).root
        atomic_json(root, "input.json", packet)
        queue.service.current(dataset.id, dataset.revision)
        queue.jobs.prepared(identifier)
    except (WebError, OSError, ValueError):
        queue.jobs.update(
            identifier,
            status="failed",
            error_code="sar_input_unpublished",
            error_message="SAR input was not published; no worker was started.",
        )
        raise
    queue.wake.set()
    return value
