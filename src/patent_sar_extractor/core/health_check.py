#!/usr/bin/env python3
"""Runtime health checks for PatentSAR Extractor."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, asdict
from pathlib import Path

from patent_sar_extractor.contracts import HEALTH_REPORT_SCHEMA, HEALTH_REPORT_SCHEMA_VERSION, artifact_identity
from patent_sar_extractor.artifact_io import write_json_atomic
from patent_sar_extractor.core.runtime_env import (
    build_gpu_env,
    host_gpu_compute_capability,
    tensorflow_cuda_caps_support_gpu,
)
from patent_sar_extractor.core.env_runner import get_python


DECIMER_PYTHON = get_python("decimer")
SMILES_PYTHON = get_python("smiles_engine")


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str = ""
    required: bool = True


def _run(cmd: list[str], timeout: int = 30, env: dict | None = None) -> subprocess.CompletedProcess:
    child_env = dict(env) if env is not None else os.environ.copy()
    child_env.pop("PYTHONPATH", None)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=child_env)


def gpu_env() -> dict[str, str]:
    return build_gpu_env(python_path=DECIMER_PYTHON)


def _env_root(python_path: str) -> Path | None:
    path = Path(python_path)
    if path.name.startswith("python") and path.parent.name == "bin":
        return path.parent.parent
    return None


def _python_exists(python_path: str) -> bool:
    if os.path.sep in python_path or (os.path.altsep and os.path.altsep in python_path):
        return Path(python_path).is_file()
    return shutil.which(python_path) is not None


_TENSORFLOW_GPU_PROBE_MARKER = "PATENTSAR_GPU_PROBE="


def _parse_tensorflow_gpu_probe(stdout: str) -> dict:
    for line in str(stdout or "").splitlines():
        if line.startswith(_TENSORFLOW_GPU_PROBE_MARKER):
            try:
                payload = json.loads(line[len(_TENSORFLOW_GPU_PROBE_MARKER):])
            except json.JSONDecodeError:
                return {}
            return payload if isinstance(payload, dict) else {}
    return {}


def _tensorflow_gpu_probe_is_compatible(probe: dict, host_capability: str) -> bool:
    devices = probe.get("devices", []) if isinstance(probe, dict) else []
    tf_capabilities = probe.get("cuda_compute_capabilities", []) if isinstance(probe, dict) else []
    return (
        isinstance(devices, list)
        and bool(devices)
        and isinstance(tf_capabilities, list)
        and tensorflow_cuda_caps_support_gpu(tf_capabilities, host_capability)
    )


def run_checks(require_gpu: bool = True) -> dict:
    results: list[CheckResult] = []

    def add(name: str, ok: bool, detail: str = "", required: bool = True):
        results.append(CheckResult(name=name, ok=ok, detail=detail, required=required))

    try:
        # Detect WSL environment from within (not via wsl.exe)
        if os.path.exists("/proc/version") and "microsoft" in open("/proc/version").read().lower():
            add("wsl", True, "WSL2 environment detected")
        else:
            add("wsl", False, "Not running in WSL", required=False)
    except Exception as e:
        add("wsl", False, str(e), required=False)

    try:
        nvidia_smi = shutil.which("nvidia-smi") or "/usr/lib/wsl/lib/nvidia-smi"
        proc = _run([nvidia_smi], timeout=20)
        add(
            "nvidia-smi",
            proc.returncode == 0,
            (proc.stdout or proc.stderr).strip().splitlines()[0] if (proc.stdout or proc.stderr) else "",
            required=require_gpu,
        )
    except Exception as e:
        add("nvidia-smi", False, str(e), required=require_gpu)

    add("decimer_python", _python_exists(DECIMER_PYTHON), DECIMER_PYTHON)
    add("smiles_python", _python_exists(SMILES_PYTHON), SMILES_PYTHON, required=False)
    try:
        proc = _run(
            [DECIMER_PYTHON, "-c", "import decimer_segmentation; print(decimer_segmentation.__version__)"],
            timeout=60,
        )
        add(
            "decimer_segmentation",
            proc.returncode == 0,
            (proc.stdout or proc.stderr).strip()[-1000:],
        )
    except Exception as exc:
        add("decimer_segmentation", False, str(exc))
    try:
        model_env = os.environ.copy()
        model_env.update({
            "CUDA_VISIBLE_DEVICES": "-1",
            "PATENTSAR_DECIMER_ENABLE_GPU": "0",
            "TF_CPP_MIN_LOG_LEVEL": "3",
        })
        proc = _run(
            [
                DECIMER_PYTHON,
                "-c",
                (
                    "from decimer_segmentation import get_model\n"
                    "model = get_model()\n"
                    "print('PATENTSAR_DECIMER_MODEL_OK=' + type(model).__name__)\n"
                ),
            ],
            timeout=180,
            env=model_env,
        )
        detail = (proc.stdout or proc.stderr).strip()[-1200:]
        add(
            "decimer_model",
            proc.returncode == 0 and "PATENTSAR_DECIMER_MODEL_OK=" in (proc.stdout or ""),
            detail,
        )
    except Exception as exc:
        add("decimer_model", False, str(exc))
    decimer_env = _env_root(DECIMER_PYTHON)
    if decimer_env:
        ptxas_path = decimer_env / "bin" / "ptxas"
        libdevice_path = decimer_env / "nvvm" / "libdevice" / "libdevice.10.bc"
        add("decimer_ptxas", ptxas_path.is_file(), str(ptxas_path), required=require_gpu)
        add("decimer_libdevice", libdevice_path.is_file(), str(libdevice_path), required=require_gpu)
    else:
        add("decimer_ptxas", False, "decimer python is not a conda-style path", required=False)
        add("decimer_libdevice", False, "decimer python is not a conda-style path", required=False)
    add("wsl_libcuda", Path("/usr/lib/wsl/lib/libcuda.so.1").is_file(), "/usr/lib/wsl/lib/libcuda.so.1", required=require_gpu)

    try:
        proc = _run(
            [
                DECIMER_PYTHON,
                "-c",
                (
                    "import json, tensorflow as tf\n"
                    "print('PATENTSAR_GPU_PROBE=' + json.dumps({"
                    "'devices': [device.name for device in tf.config.list_physical_devices('GPU')], "
                    "'cuda_compute_capabilities': tf.sysconfig.get_build_info().get('cuda_compute_capabilities', [])"
                    "}))\n"
                ),
            ],
            timeout=90,
            env=gpu_env(),
        )
        probe = _parse_tensorflow_gpu_probe(proc.stdout or "")
        host_capability = host_gpu_compute_capability()
        compatible = proc.returncode == 0 and _tensorflow_gpu_probe_is_compatible(probe, host_capability)
        detail = {
            "host_compute_capability": host_capability or None,
            "tensorflow_devices": probe.get("devices", []),
            "tensorflow_cuda_compute_capabilities": probe.get("cuda_compute_capabilities", []),
        }
        stderr_tail = (proc.stderr or "").strip()[-500:]
        if stderr_tail:
            detail["diagnostic_tail"] = stderr_tail
        add(
            "tensorflow_gpu",
            compatible,
            json.dumps(detail, ensure_ascii=False, sort_keys=True),
            required=require_gpu,
        )
    except Exception as e:
        add("tensorflow_gpu", False, str(e), required=require_gpu)

    try:
        proc = _run(
            [
                SMILES_PYTHON,
                "-c",
                "import torch; print({'cuda': torch.cuda.is_available(), 'count': torch.cuda.device_count(), 'name': torch.cuda.get_device_name(0) if torch.cuda.is_available() else ''})",
            ],
            timeout=60,
            env=build_gpu_env(python_path=SMILES_PYTHON),
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        add("pytorch_gpu", proc.returncode == 0 and "'cuda': True" in out, out.strip()[-1000:], required=False)
    except Exception as e:
        add("pytorch_gpu", False, str(e), required=False)

    try:
        proc = _run([SMILES_PYTHON, "-c", "import rdkit; print(rdkit.__version__)"], timeout=20)
        add("rdkit", proc.returncode == 0, (proc.stdout or proc.stderr).strip())
    except Exception as e:
        add("rdkit", False, str(e))

    try:
        pdf_python = get_python("pymupdf") or sys.executable or "python3"
        proc = _run([pdf_python, "-c", "import fitz, rapidocr_onnxruntime; print('ok')"], timeout=20)
        add("ocr_pdf_deps", proc.returncode == 0, (proc.stdout or proc.stderr).strip())
    except Exception as e:
        add("ocr_pdf_deps", False, str(e))

    required_failed = [r for r in results if r.required and not r.ok]
    return {
        **artifact_identity(HEALTH_REPORT_SCHEMA, HEALTH_REPORT_SCHEMA_VERSION),
        "ok": not required_failed,
        "required_failed": [r.name for r in required_failed],
        "checks": [asdict(r) for r in results],
    }


def write_health_report(path: str, require_gpu: bool = True) -> dict:
    report = run_checks(require_gpu=require_gpu)
    write_json_atomic(path, report)
    return report


def main():
    report = run_checks(require_gpu=True)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    raise SystemExit(0 if report["ok"] else 2)


if __name__ == "__main__":
    main()
