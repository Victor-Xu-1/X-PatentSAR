"""CPU-only constrained-rescue adapter; never registered as a primary engine."""

from __future__ import annotations

import os
from pathlib import Path

from patent_sar_extractor.core.env_runner import (
    configured_model_environment,
    get_python,
)

from .owned_engine import OwnedOCSREngine


class MolScribeEngine(OwnedOCSREngine):
    name = "molscribe"
    memory_headroom_mb = 2304

    def __init__(self, python_bin=None, batch_wrapper_script=None, env_extra=None):
        super().__init__(
            python_bin or get_python("molscribe"),
            batch_wrapper_script
            or str(Path(__file__).resolve().parents[1] / "wrapper_molscribe_batch.py"),
            env_extra,
        )

    def _build_env(self) -> dict[str, str]:
        environment = os.environ.copy()
        environment.pop("PYTHONPATH", None)
        environment.update(configured_model_environment())
        environment.update(self._env_extra)
        environment.update(
            CUDA_VISIBLE_DEVICES="-1",
            LD_PRELOAD="",
            OMP_NUM_THREADS="2",
            OPENBLAS_NUM_THREADS="1",
            MKL_NUM_THREADS="2",
            TORCH_FORCE_WEIGHTS_ONLY_LOAD="1",
            LD_LIBRARY_PATH=str(Path(self.python_bin).parent.parent / "lib"),
        )
        return environment

    def is_available(self) -> bool:
        value = self._build_env().get("PATENTSAR_MOLSCRIBE_MODEL_DIR")
        return super().is_available() and bool(value and Path(value).is_dir())
