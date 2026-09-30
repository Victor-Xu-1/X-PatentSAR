"""
DECIMER OCSR Engine (Subprocess Mode).

Runs DECIMER in an isolated conda environment so its TensorFlow/Python 3.10
runtime cannot contaminate the Python 3.12 application environment.

The engine calls wrapper_decimer.py which runs inside the `decimer`
conda environment and returns JSON on stdout.
"""

import json
import os
import select
import subprocess
import threading
import time
import uuid
from typing import Optional

from patent_sar_extractor.core.env_runner import get_python

from .base_engine import BaseOCSREngine

# Default paths
_DECIMER_PYTHON = get_python("decimer")
_WRAPPER_SCRIPT = os.path.join(os.path.dirname(os.path.dirname(__file__)), "wrapper_decimer.py")
_BATCH_WRAPPER_SCRIPT = os.path.join(os.path.dirname(os.path.dirname(__file__)), "wrapper_decimer_batch.py")


class DECIMEREngine(BaseOCSREngine):
    """DECIMER OCSR engine - subprocess mode via isolated conda env.

    DECIMER depends on a dedicated TensorFlow/Python 3.10 runtime. This engine
    runs it in a separate `decimer` conda environment via subprocess.

    DECIMER V2 model is auto-downloaded to ~/.data/DECIMER-V2/ on first use.
    CPU inference is fast (~8s/image).
    """

    name = "decimer"

    def __init__(
        self,
        python_bin: Optional[str] = None,
        wrapper_script: Optional[str] = None,
    ):
        """Initialize DECIMER subprocess engine.

        Args:
            python_bin: Path to decimer conda env python executable.
                       Default: resolved from DECIMER_PYTHON/env_paths.yaml.
            wrapper_script: Path to wrapper_decimer.py script.
                          Default: same directory as this file.
        """
        self.python_bin = python_bin or os.environ.get(
            "DECIMER_PYTHON", _DECIMER_PYTHON
        )
        self.wrapper_script = wrapper_script or os.environ.get(
            "DECIMER_WRAPPER", _WRAPPER_SCRIPT
        )
        self.batch_wrapper_script = os.environ.get("DECIMER_BATCH_WRAPPER", _BATCH_WRAPPER_SCRIPT)
        self._worker: subprocess.Popen | None = None
        self._worker_lock = threading.Lock()

    def is_available(self) -> bool:
        """Check if DECIMER is available (python bin + wrapper script)."""
        if not os.path.isfile(self.python_bin):
            return False
        if not os.path.isfile(self.wrapper_script):
            return False
        return True

    def _persistent_enabled(self) -> bool:
        return os.environ.get("PATENTSAR_DECIMER_PERSISTENT", "1").strip().lower() not in {"0", "false", "no"}

    def _build_env(self) -> dict:
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        env["TF_CPP_MIN_LOG_LEVEL"] = "3"
        env["CUDA_VISIBLE_DEVICES"] = os.environ.get("CUDA_VISIBLE_DEVICES", "0")
        wsl_cuda_libs = "/usr/lib/wsl/lib"
        conda_env = os.path.dirname(os.path.dirname(self.python_bin))
        conda_lib = os.path.join(conda_env, "lib")
        old_ld = env.get("LD_LIBRARY_PATH", "")
        env["LD_LIBRARY_PATH"] = ":".join(
            p for p in [wsl_cuda_libs, conda_lib, old_ld] if p
        )
        env["PATH"] = ":".join(
            p for p in [os.path.join(conda_env, "bin"), env.get("PATH", "")] if p
        )
        env["XLA_FLAGS"] = f"--xla_gpu_cuda_data_dir={conda_env}"
        return env

    def _stop_worker(self) -> None:
        worker = self._worker
        self._worker = None
        if worker is None:
            return
        try:
            if worker.stdin:
                worker.stdin.write("__quit__\n")
                worker.stdin.flush()
        except Exception:
            pass
        try:
            worker.terminate()
        except Exception:
            pass

    def _read_worker_line(self, timeout: int) -> Optional[str]:
        if self._worker is None or self._worker.stdout is None:
            return None
        ready, _write, _err = select.select([self._worker.stdout], [], [], timeout)
        if not ready:
            return None
        return self._worker.stdout.readline()

    def _ensure_worker(self, startup_timeout: int = 120) -> bool:
        if self._worker is not None and self._worker.poll() is None:
            return True
        if not os.path.isfile(self.batch_wrapper_script):
            return False
        cmd = [self.python_bin, self.batch_wrapper_script]
        try:
            self._worker = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
                env=self._build_env(),
            )
            line = self._read_worker_line(startup_timeout)
            if not line:
                self._stop_worker()
                return False
            payload = json.loads(line)
            if payload.get("status") != "ready":
                self._stop_worker()
                return False
            return True
        except Exception:
            self._stop_worker()
            return False

    def _predict_persistent(self, image_path: str, timeout: int) -> Optional[dict]:
        with self._worker_lock:
            if not self._ensure_worker():
                return None
            if self._worker is None or self._worker.stdin is None:
                return None
            request_id = uuid.uuid4().hex
            start = time.time()
            try:
                self._worker.stdin.write(json.dumps({
                    "id": request_id,
                    "image_path": image_path,
                }, ensure_ascii=False) + "\n")
                self._worker.stdin.flush()
                line = self._read_worker_line(timeout)
                elapsed = time.time() - start
                if not line:
                    self._stop_worker()
                    return self._make_timeout_result(timeout)
                output = json.loads(line)
            except Exception as exc:
                self._stop_worker()
                return self._make_failed_result(f"DECIMER persistent worker error: {exc}")

            if output.get("id") != request_id:
                self._stop_worker()
                return self._make_failed_result("DECIMER persistent worker response id mismatch")
            if output.get("status") == "success":
                return self._make_result(
                    status="success",
                    raw_smiles=output.get("smiles", ""),
                    elapsed_sec=elapsed,
                )
            return self._make_result(
                status="failed",
                error=output.get("error", "Unknown DECIMER error"),
                elapsed_sec=elapsed,
            )

    def predict(self, image_path: str, timeout: int = 60) -> dict:
        """Predict SMILES from a structure image using DECIMER via subprocess.

        Args:
            image_path: Path to structure crop image.
            timeout: Max seconds for prediction. Default 60s (CPU ~8s/image).

        Returns:
            Standardized result dict.
        """
        start = time.time()

        if not os.path.isfile(image_path):
            return self._make_failed_result(f"Image not found: {image_path}")

        if not self.is_available():
            return self._make_unavailable_result(
                f"DECIMER not available: python={self.python_bin}, "
                f"wrapper={self.wrapper_script}"
            )

        if self._persistent_enabled():
            persistent_result = self._predict_persistent(image_path, timeout)
            if persistent_result is not None:
                return persistent_result

        try:
            cmd = [
                self.python_bin,
                self.wrapper_script,
                image_path,
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=self._build_env(),
            )

            elapsed = time.time() - start

            if result.returncode != 0:
                stderr = result.stderr.strip()[:500] if result.stderr else ""
                return self._make_result(
                    status="failed",
                    error=f"DECIMER subprocess error (rc={result.returncode}): {stderr}",
                    elapsed_sec=elapsed,
                )

            # Parse JSON output from stdout
            stdout = result.stdout.strip()
            if not stdout:
                return self._make_result(
                    status="failed",
                    error="DECIMER returned empty output",
                    elapsed_sec=elapsed,
                )

            try:
                output = json.loads(stdout)
            except json.JSONDecodeError as e:
                return self._make_result(
                    status="failed",
                    error=f"DECIMER output parse error: {e}\nRaw: {stdout[:200]}",
                    elapsed_sec=elapsed,
                )

            if output.get("status") == "success":
                smiles = output.get("smiles", "")
                return self._make_result(
                    status="success",
                    raw_smiles=smiles,
                    elapsed_sec=elapsed,
                )
            else:
                error = output.get("error", "Unknown DECIMER error")
                return self._make_result(
                    status="failed",
                    error=error,
                    elapsed_sec=elapsed,
                )

        except subprocess.TimeoutExpired:
            return self._make_timeout_result(timeout)
        except FileNotFoundError:
            return self._make_unavailable_result(
                f"DECIMER python not found: {self.python_bin}"
            )
        except Exception as e:
            return self._make_failed_result(f"DECIMER engine error: {e}")
