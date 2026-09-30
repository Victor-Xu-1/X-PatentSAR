"""Environment worker adapter over the single existing owned-process supervisor."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from patent_sar_extractor.paths import PACKAGE_IMPORT_ROOT, PACKAGE_ROOT

from .processes import RunSpec, SubprocessRunner


class EnvironmentProcessRunner(SubprocessRunner):
    def command(self, spec: RunSpec) -> list[str]:
        return [
            sys.executable,
            str(PACKAGE_ROOT / "workers" / "environment_install_worker.py"),
            "--plan",
            str(Path(spec.output_dir) / "environment-plan.json"),
        ]

    def environment(self, spec: RunSpec) -> dict[str, str]:
        # Installer subprocesses must not inherit LLM/Git/cloud credentials or
        # user-supplied package registries from the extraction process environment.
        allowed = {"PATH", "LANG", "LC_ALL", "SSL_CERT_FILE", "SSL_CERT_DIR"}
        env = {key: value for key, value in os.environ.items() if key in allowed}
        env.update(
            {
                "PYTHONPATH": str(PACKAGE_IMPORT_ROOT),
                "PYTHONUNBUFFERED": "1",
                "PYTHONDONTWRITEBYTECODE": "1",
                "CUDA_VISIBLE_DEVICES": "-1",
                "OMP_NUM_THREADS": "1",
                "OPENBLAS_NUM_THREADS": "1",
                "MKL_NUM_THREADS": "1",
                "TF_NUM_INTRAOP_THREADS": "1",
                "TF_NUM_INTEROP_THREADS": "1",
                "UV_CONCURRENT_DOWNLOADS": "3",
                "UV_CONCURRENT_INSTALLS": "2",
                "UV_HTTP_TIMEOUT": "30",
                "UV_HTTP_RETRIES": "2",
                "UV_NO_PROGRESS": "1",
                "PIP_DISABLE_PIP_VERSION_CHECK": "1",
                "PIP_NO_INPUT": "1",
                "XDG_CACHE_HOME": str(Path(spec.output_dir) / "cache"),
                "TMPDIR": str(Path(spec.output_dir) / "tmp"),
            }
        )
        for name in ("cache", "tmp"):
            directory = Path(spec.output_dir) / name
            directory.mkdir(mode=0o700, exist_ok=True)
        return env
