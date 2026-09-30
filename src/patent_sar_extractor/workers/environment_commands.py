"""Bounded owned installer children; only fixed recipes construct commands."""

from __future__ import annotations

import os
import selectors
import subprocess
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

from patent_sar_extractor.web.analysis_children import Children, alive, read_child


def install_environment(cache_root: Path, operation_dir: Path) -> dict[str, str]:
    env = {
        "PATH": "/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "CUDA_VISIBLE_DEVICES": "-1",
        "OMP_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "TF_NUM_INTRAOP_THREADS": "1",
        "TF_NUM_INTEROP_THREADS": "1",
        "PYTHONUNBUFFERED": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "UV_CACHE_DIR": str(cache_root / "uv"),
        "UV_HTTP_RETRIES": "1",
        "UV_HTTP_TIMEOUT": "30",
        "UV_NO_CONFIG": "1",
        "UV_NO_PROGRESS": "1",
        "UV_PYTHON_INSTALL_DIR": str(operation_dir / "python-downloads"),
        "TMPDIR": str(operation_dir),
        "XDG_CACHE_HOME": str(cache_root),
        "MPLCONFIGDIR": str(operation_dir / "matplotlib"),
    }
    for name in ("HTTPS_PROXY", "HTTP_PROXY"):
        value = os.environ.get(name)
        if value:
            parsed = urlsplit(value)
            if (
                not parsed.username
                and not parsed.password
                and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
            ):
                env[name] = value
    return env


def run_command(
    command: list[str],
    *,
    operation_dir: Path,
    env: dict[str, str],
    cancel: threading.Event,
    timeout: float = 3600,
) -> None:
    if cancel.is_set():
        raise InterruptedError("Operation cancelled")
    child = subprocess.Popen(
        command,
        cwd=operation_dir,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    owner = None
    selector = selectors.DefaultSelector()
    total = 0
    deadline = time.monotonic() + min(timeout, 3600)
    try:
        identity = read_child(child.pid)
        if identity is None:
            raise RuntimeError("Installer child ownership could not be established")
        owner = Children(identity, 4608 * 1024 * 1024)
        assert child.stdout is not None
        os.set_blocking(child.stdout.fileno(), False)
        selector.register(child.stdout, selectors.EVENT_READ)
        while selector.get_map() or child.poll() is None:
            owner.observe()
            if cancel.is_set():
                raise InterruptedError("Operation cancelled")
            if time.monotonic() >= deadline:
                raise TimeoutError("Installer stage exceeded its bounded lifetime")
            for key, _ in selector.select(0.1):
                chunk = os.read(key.fd, 65536)
                if not chunk:
                    selector.unregister(key.fileobj)
                total += len(chunk)
                if total > 8 * 1024 * 1024:
                    raise RuntimeError("Installer output exceeded its bound")
        if child.wait(timeout=2) != 0:
            raise RuntimeError("Pinned installer command failed")
    finally:
        selector.close()
        if owner is not None:
            owner.stop()
        if child.poll() is None:
            child.kill()
        child.wait(timeout=2)
        if child.stdout:
            child.stdout.close()
        if owner is not None and any(alive(c) for c in owner.observed.values()):
            raise RuntimeError("Owned installer child cleanup was not verified")
