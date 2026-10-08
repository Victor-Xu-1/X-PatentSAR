"""One owned SAR attempt and output validator; queue lifecycle stays separate."""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from typing import TYPE_CHECKING

from ..analysis_lease import analysis_lease
from ..analysis_process import BoundedAnalysisRunner
from ..errors import WebError
from ..storage import now
from .assets import atomic_json, digest
from .models import Pair, SARJob
from .ownership import intent, started

if TYPE_CHECKING:
    from .queue import SARQueue


def execute(queue: SARQueue, row: dict, runner: BoundedAnalysisRunner) -> None:
    value = SARJob.model_validate_json(row["payload"])
    spec = json.loads(row["spec"])
    safe = queue.service.assets.job_files(row["root"], value.id)
    lease = analysis_lease(queue.service.workspace.store.root)
    queue.runner = runner
    queue.active_id = value.id
    queue.cancel_signal.clear()
    if queue.jobs.record(value.id)["cancel_requested"]:
        queue.cancel_signal.set()
    entered = False
    try:
        lease.__enter__()
        entered = True
        queue.service.current(value.dataset_id)
        intent(safe.root, value.id, value.input_sha256, spec["attempt_id"])
        result = runner.run(
            [sys.executable, "-m", "patent_sar_extractor.workers.sar_worker"],
            {"root": str(safe.root), "input_sha256": value.input_sha256},
            cwd=safe.root,
            env=_environment(safe.root),
            timeout=180,
            cancel=_JobCancel(queue, value.id),
            on_start=lambda child: started(
                safe.root, value.id, value.input_sha256, spec["attempt_id"], child
            ),
        )
        if (
            result.get("input_sha256") != value.input_sha256
            or result.get("engine_sha256") != spec["engine_sha256"]
            or type(result.get("chunks")) is not int
        ):
            raise WebError(
                502,
                "sar_result_invalid",
                "SAR result does not match its declared input.",
            )
        pairs = collect(safe, value, result["chunks"], spec["engine_sha256"])
        queue.service.current(value.dataset_id)
        queue.jobs.publish(value.id, pairs, value.total)
    except WebError as error:
        cancelled = queue.jobs.record(value.id)["cancel_requested"]
        queue.jobs.update(
            value.id,
            status="interrupted"
            if queue.closed.is_set()
            else "cancelled"
            if cancelled
            else "failed",
            finished_at=now(),
            error_code=error.code,
            error_message=error.message,
        )
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, sqlite3.Error):
        queue.jobs.update(
            value.id,
            status="failed",
            finished_at=now(),
            error_code="sar_worker_failed",
            error_message="SAR analysis could not complete; source and checkpoints were retained.",
        )
    finally:
        try:
            runner.close()
            atomic_json(
                safe.root,
                f"cleanup-{spec['attempt_id']}.json",
                {
                    "schema": 1,
                    "job_id": value.id,
                    "input_sha256": value.input_sha256,
                    "verified": True,
                },
            )
            queue.jobs.cleaned(value.id, spec["attempt_id"])
        except (
            WebError,
            OSError,
            ValueError,
            RuntimeError,
            KeyError,
            TypeError,
            sqlite3.Error,
        ):
            if entered:
                queue.retained_lease = lease
            queue.jobs.update(
                value.id,
                status="failed",
                error_code="sar_process_unverified",
                error_message="SAR worker cleanup could not be verified.",
            )
        else:
            if entered:
                lease.__exit__(None, None, None)
            queue.runner = None
        queue.active_id = None


def collect(safe, value: SARJob, count: int, identity: str) -> list[Pair]:
    if not 0 <= count <= 1000:
        raise WebError(502, "sar_result_invalid", "SAR result chunk count is invalid.")
    output = []
    for index in range(count):
        packet = safe.json(f"chunk-{index:04d}.json", optional=False)
        if (
            not isinstance(packet, dict)
            or packet.get("input_sha256") != value.input_sha256
            or packet.get("engine_sha256") != identity
            or packet.get("start") != index * 25
            or not isinstance(packet.get("pairs"), list)
            or len(packet["pairs"]) > 25
            or digest(packet["pairs"]) != packet.get("pairs_sha256")
        ):
            raise WebError(
                502, "sar_result_invalid", "SAR result checkpoint is invalid."
            )
        output.extend(Pair.model_validate(item) for item in packet["pairs"])
    return output


class _JobCancel:
    def __init__(self, queue: SARQueue, identifier: str):
        self.queue, self.identifier = queue, identifier

    def is_set(self) -> bool:
        return self.queue.closed.is_set() or self.queue.cancel_signal.is_set()


def _environment(root) -> dict[str, str]:
    values = {
        "PATH": "/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "TMPDIR": str(root),
        "PYTHONDONTWRITEBYTECODE": "1",
        "OMP_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "CUDA_VISIBLE_DEVICES": "-1",
    }
    # Explicit source-test selection only; production has no implicit source fallback.
    if os.environ.get("PYTHONPATH"):
        values["PYTHONPATH"] = os.environ["PYTHONPATH"]
    return values
