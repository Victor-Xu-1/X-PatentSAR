"""DECIMER policy adapter using the shared owned OCSR process lifecycle."""

from __future__ import annotations

import os
from pathlib import Path

from patent_sar_extractor.core.env_runner import (
    configured_model_environment,
    get_python,
)
from patent_sar_extractor.core.runtime_env import build_gpu_env

from .owned_engine import OwnedOCSREngine

_WRAPPER = str(Path(__file__).resolve().parents[1] / "wrapper_decimer_batch.py")


class DECIMEREngine(OwnedOCSREngine):
    name = "decimer"

    def __init__(self, python_bin=None, batch_wrapper_script=None, env_extra=None):
        super().__init__(
            python_bin or get_python("decimer"),
            batch_wrapper_script or os.environ.get("DECIMER_BATCH_WRAPPER", _WRAPPER),
            env_extra,
        )

    def _build_env(self) -> dict[str, str]:
        environment = os.environ.copy()
        environment.pop("PYTHONPATH", None)
        environment.update(configured_model_environment())
        environment.update(self._env_extra)
        environment.setdefault("PATENTSAR_DECIMER_ENABLE_GPU", "0")
        environment.setdefault("PATENTSAR_DECIMER_CPU_THREADS", "2")
        if environment["PATENTSAR_DECIMER_ENABLE_GPU"] != "1":
            environment.update(
                CUDA_VISIBLE_DEVICES="-1",
                LD_PRELOAD="",
                LD_LIBRARY_PATH=str(Path(self.python_bin).parent.parent / "lib"),
            )
        else:
            environment = build_gpu_env(
                python_path=self.python_bin, base_env=environment
            )
        environment["TF_CPP_MIN_LOG_LEVEL"] = "2"
        return environment
