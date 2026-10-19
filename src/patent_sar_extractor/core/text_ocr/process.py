"""Reuse the owned JSONL carrier with text-specific cancellation and RSS bounds."""

from __future__ import annotations

import os
import re
import threading
import time
from pathlib import Path

from patent_sar_extractor.core.ocsr.resource_budget import worker_resident_mb
from patent_sar_extractor.core.ocsr.worker_process import (
    JsonLineWorker,
    WorkerProtocolError,
)

from .identity import recipe
from .protocol import MAX_RSS_MB


class TextOCRCancelled(RuntimeError):
    pass


def remaining(deadline: float, cancel: threading.Event | None) -> float:
    if cancel is not None and cancel.is_set():
        raise TextOCRCancelled("Auxiliary text OCR was cancelled")
    value = deadline - time.monotonic()
    if value <= 0:
        raise TimeoutError("Auxiliary text OCR deadline exceeded")
    return value


def receive(worker, deadline: float, cancel: threading.Event | None) -> dict:
    while True:
        budget = remaining(deadline, cancel)
        rss = worker_resident_mb(worker.process.pid)
        if rss is not None and rss > MAX_RSS_MB:
            raise WorkerProtocolError(
                "Auxiliary text OCR exceeded its resident memory budget"
            )
        try:
            return worker.receive(min(0.2, budget))
        except TimeoutError:
            continue


def environment(models: Path, workspace: Path) -> dict[str, str]:
    # No parent provider credentials, Python packages, proxies or GPU overrides.
    return {
        "PATH": "/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TMPDIR": str(workspace),
        "CUDA_VISIBLE_DEVICES": "-1",
        "OMP_NUM_THREADS": "2",
        "MKL_NUM_THREADS": "2",
        "OPENBLAS_NUM_THREADS": "2",
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPYCACHEPREFIX": str(workspace / "bytecode"),
        "PATENTSAR_TEXT_OCR_MODEL_DIR": str(models),
        "PATENTSAR_TEXT_OCR_INPUT_ROOT": str(workspace),
        "PADDLE_PDX_CACHE_HOME": str(workspace / "paddlex"),
        "PADDLE_EXTENSION_DIR": str(workspace / "extensions"),
        "HF_HOME": str(workspace / "huggingface"),
        "HF_HUB_OFFLINE": "1",
        "HF_HUB_DISABLE_TELEMETRY": "1",
        "PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK": "True",
        "DO_NOT_TRACK": "1",
        "PATENTSAR_WORKER_PARENT_PID": str(os.getpid()),
    }


def model_stamp(models: Path) -> tuple:
    values = []
    for name in ("inference.json", "inference.pdiparams", "inference.yml"):
        path = models / name
        if any(p.is_symlink() for p in (path, *path.parents)):
            raise ValueError("Auxiliary text OCR model path is unsafe")
        info = path.stat()
        values.append((name, info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns))
    return tuple(values)


def query_text_identity(command, environment, models, deadline, cancel):
    worker = JsonLineWorker([*command, "--identity"], environment)
    try:
        identity = receive(worker, deadline, cancel)
        spec = recipe()
        fields = {
            "fingerprint",
            "model_name",
            "model_revision",
            "adapter_version",
            "versions",
            "device",
            "model_directory",
        }
        if (
            set(identity) != fields
            or any(
                identity[key] != spec[key]
                for key in ("model_name", "model_revision", "adapter_version")
            )
            or identity["versions"] != spec["distributions"]
            or identity["device"] != "cpu"
            or identity["model_directory"] != str(models)
            or not isinstance(identity["fingerprint"], str)
            or not re.fullmatch(r"[a-f0-9]{64}", identity["fingerprint"])
        ):
            raise WorkerProtocolError("Auxiliary text OCR identity is invalid")
        return identity
    finally:
        worker.close()
