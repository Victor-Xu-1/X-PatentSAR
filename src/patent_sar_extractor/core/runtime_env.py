"""
Unified runtime environment helpers.

This module keeps GPU-related runtime configuration in one place so pipeline
steps do not each hand-roll their own CUDA / WSL library setup.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path


def _dedupe_paths(parts: list[str]) -> str:
    seen: set[str] = set()
    ordered: list[str] = []
    for part in parts:
        for piece in str(part or "").split(":"):
            piece = piece.strip()
            if not piece or piece in seen:
                continue
            seen.add(piece)
            ordered.append(piece)
    return ":".join(ordered)


def env_root_from_python(python_path: str) -> str:
    py = Path(python_path).resolve()
    return str(py.parent.parent)


def parse_compute_capability(value: str) -> tuple[int, int] | None:
    text = str(value or "").strip().lower()
    match = re.search(r"(?:sm_|compute_)?(\d+)(?:[._]?(\d+))?", text)
    if not match:
        return None
    raw_major = match.group(1)
    raw_minor = match.group(2)
    if raw_minor is None and len(raw_major) >= 2:
        return int(raw_major[:-1]), int(raw_major[-1])
    return int(raw_major), int(raw_minor or 0)


def tensorflow_cuda_caps_support_gpu(tf_caps: list[str], gpu_capability: str) -> bool:
    """Fail closed when a TensorFlow wheel does not support the GPU family."""

    gpu = parse_compute_capability(gpu_capability)
    if gpu is None:
        return False
    parsed_caps = [
        cap for cap in (parse_compute_capability(item) for item in tf_caps)
        if cap is not None
    ]
    if not parsed_caps:
        return False
    if gpu in parsed_caps:
        return True
    return gpu[0] <= max(cap[0] for cap in parsed_caps)


def host_gpu_compute_capability(nvidia_smi_path: str = "") -> str:
    """Return the first visible NVIDIA GPU compute capability, or an empty string."""

    executable = (
        nvidia_smi_path
        or shutil.which("nvidia-smi")
        or "/usr/lib/wsl/lib/nvidia-smi"
    )
    try:
        proc = subprocess.run(
            [executable, "--query-gpu=compute_cap", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if proc.returncode != 0:
        return ""
    capabilities = [line.strip() for line in (proc.stdout or "").splitlines() if line.strip()]
    return capabilities[0] if capabilities else ""


def build_gpu_env(
    *,
    python_path: str = "",
    base_env: dict[str, str] | None = None,
    extra_env: dict[str, str] | None = None,
) -> dict[str, str]:
    """
    Build a consistent WSL/CUDA runtime environment for subprocesses.

    We keep this conservative:
    - prefer WSL CUDA shim libraries
    - prepend env-local lib/bin paths
    - avoid forcing a vendor-specific CUDA root unless one exists
    """
    env = dict(base_env or os.environ)
    env_root = env_root_from_python(python_path) if python_path else ""

    lib_dirs = [
        "/usr/lib/wsl/lib",
        f"{env_root}/lib" if env_root else "",
        f"{env_root}/targets/x86_64-linux/lib" if env_root else "",
        "/usr/local/cuda/lib64",
        env.get("LD_LIBRARY_PATH", ""),
    ]
    bin_dirs = [
        f"{env_root}/bin" if env_root else "",
        "/usr/local/cuda/bin",
        env.get("PATH", ""),
    ]

    env["CUDA_VISIBLE_DEVICES"] = env.get("CUDA_VISIBLE_DEVICES", "0")
    env["CUDA_DEVICE_ORDER"] = env.get("CUDA_DEVICE_ORDER", "PCI_BUS_ID")
    env["LD_LIBRARY_PATH"] = _dedupe_paths(lib_dirs)
    env["PATH"] = _dedupe_paths(bin_dirs)
    env["TF_FORCE_GPU_ALLOW_GROWTH"] = env.get("TF_FORCE_GPU_ALLOW_GROWTH", "true")

    if env_root:
        env.setdefault("XLA_FLAGS", f"--xla_gpu_cuda_data_dir={env_root}")

    libcuda = Path("/usr/lib/wsl/lib/libcuda.so.1")
    if libcuda.is_file():
        ld_preload_parts = [str(libcuda), env.get("LD_PRELOAD", "")]
        env["LD_PRELOAD"] = _dedupe_paths(ld_preload_parts)

    if extra_env:
        env.update(extra_env)
    return env


def default_worker_count(requested: int | None, *, floor: int = 1, ceiling: int = 8, reserve_cpu: int = 2) -> int:
    if requested is not None and int(requested) > 0:
        return max(floor, min(int(requested), ceiling))
    cpu_total = os.cpu_count() or 4
    auto = max(floor, cpu_total - reserve_cpu)
    return min(auto, ceiling)
