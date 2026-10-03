"""worker policy: single application-layer policy authority."""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

from patent_sar_extractor.core.env_runner import get_python, run_snippet
from patent_sar_extractor.core.runtime_env import (
    build_gpu_env,
)
from patent_sar_extractor.core.runtime_env import (
    host_gpu_compute_capability as _host_gpu_compute_capability,
)
from patent_sar_extractor.core.runtime_env import (
    tensorflow_cuda_caps_support_gpu as _tf_cuda_caps_support_gpu,
)

logger = logging.getLogger("patent_sar_extractor")
WORKING_ROOT = Path.cwd()
_DECIMER_TF_GPU_SAFE: bool | None = None
_ACTIVITY_TIMEOUT_BASE_SECONDS = 1800
_ACTIVITY_TIMEOUT_PER_PAGE_SECONDS = 10
_ACTIVITY_TIMEOUT_MAX_SECONDS = 10800


def _gpu_env_extra(
    env_name: str = "decimer",
    extra_env: dict[str, str] | None = None,
    gpu_mode: str = "auto",
) -> dict[str, str]:
    merged_extra = dict(extra_env or {})
    if env_name in {"decimer", "smiles_engine"}:
        direct_decimer_env = env_name == "decimer"
        if gpu_mode == "force":
            merged_extra.setdefault("CUDA_VISIBLE_DEVICES", "0")
            merged_extra["PATENTSAR_DECIMER_ENABLE_GPU"] = "1"
            if direct_decimer_env:
                return build_gpu_env(
                    python_path=get_python(env_name),
                    extra_env=merged_extra,
                )
            return merged_extra
        if gpu_mode == "off" or not _decimer_tensorflow_gpu_safe():
            merged_extra["CUDA_VISIBLE_DEVICES"] = "-1"
            merged_extra["PATENTSAR_DECIMER_ENABLE_GPU"] = "0"
            merged_extra["LD_PRELOAD"] = ""
            merged_extra["LD_LIBRARY_PATH"] = ""
            merged_extra.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
            return merged_extra
        merged_extra.setdefault("CUDA_VISIBLE_DEVICES", "0")
        merged_extra["PATENTSAR_DECIMER_ENABLE_GPU"] = "1"
        if direct_decimer_env:
            return build_gpu_env(
                python_path=get_python(env_name),
                extra_env=merged_extra,
            )
        return merged_extra
    elif gpu_mode == "off":
        merged_extra["CUDA_VISIBLE_DEVICES"] = ""
    elif gpu_mode == "force":
        merged_extra.setdefault("CUDA_VISIBLE_DEVICES", "0")
    return build_gpu_env(
        python_path=get_python(env_name),
        extra_env=merged_extra,
    )


def _decimer_tensorflow_gpu_safe() -> bool:
    global _DECIMER_TF_GPU_SAFE
    if _DECIMER_TF_GPU_SAFE is not None:
        return _DECIMER_TF_GPU_SAFE
    gpu_capability = _host_gpu_compute_capability()
    if not gpu_capability:
        _DECIMER_TF_GPU_SAFE = False
        return _DECIMER_TF_GPU_SAFE
    try:
        proc = run_snippet(
            "decimer",
            (
                "import json, tensorflow as tf\n"
                "print(json.dumps(tf.sysconfig.get_build_info().get('cuda_compute_capabilities', [])))\n"
            ),
            timeout=30,
            cwd=str(WORKING_ROOT),
            env_extra={"CUDA_VISIBLE_DEVICES": ""},
        )
        caps = (
            json.loads((proc.stdout or "[]").strip().splitlines()[-1])
            if proc.returncode == 0
            else []
        )
    except Exception as exc:
        logger.warning(
            "DECIMER TensorFlow GPU probe failed; using CPU for structure extraction: %s",
            exc,
        )
        caps = []
    _DECIMER_TF_GPU_SAFE = _tf_cuda_caps_support_gpu(
        caps if isinstance(caps, list) else [], gpu_capability
    )
    if not _DECIMER_TF_GPU_SAFE:
        logger.warning(
            "DECIMER TensorFlow GPU disabled in auto mode: GPU compute capability %s is not covered by TensorFlow CUDA capabilities %s",
            gpu_capability or "unknown",
            caps or [],
        )
    return _DECIMER_TF_GPU_SAFE


def _activity_timeout_seconds(classification: dict) -> int:
    """Return a bounded timeout that scales with the classified activity workload."""

    activity_pages = (
        classification.get("activity_pages", [])
        if isinstance(classification, dict)
        else []
    )
    page_count = len(activity_pages) if isinstance(activity_pages, list) else 0
    scaled = page_count * _ACTIVITY_TIMEOUT_PER_PAGE_SECONDS
    return min(
        _ACTIVITY_TIMEOUT_MAX_SECONDS,
        max(_ACTIVITY_TIMEOUT_BASE_SECONDS, scaled),
    )


def _run_activity_rules(
    pdf_path: str,
    classification: dict,
    output_dir: str,
    include_intermediates: bool = False,
    patent_id: str = "",
) -> None:
    profile = {
        "patent_id": patent_id,
        "synthesis_pages": classification.get("synthesis_pages", []),
        "activity_pages": classification.get("activity_pages", []),
        "cpd_pattern": classification.get("cpd_pattern", r"Cpd[-\s]?(\d+)"),
        "cpd_prefix_pattern": classification.get("cpd_pattern", r"Cpd[-\s]?(\d+)"),
        "cpd_prefix": classification.get("cpd_prefix", "Cpd-"),
        "table_schema": {"type": classification.get("table_layout", "single")},
        "page_count": classification.get("page_count", 0),
        "ocr_cache_path": classification.get("ocr_cache_path", ""),
    }
    code = (
        "import sys\n"
        "from patent_sar_extractor.core.activity_extractor import extract\n"
        f"extract(pdf_path={pdf_path!r}, profile={profile!r}, output_dir={output_dir!r}, include_intermediates={bool(include_intermediates)!r})\n"
    )
    timeout_seconds = _activity_timeout_seconds(classification)
    logger.info(
        "Activity subprocess timeout: %ss for %s classified activity pages",
        timeout_seconds,
        len(profile["activity_pages"]),
    )
    try:
        proc = run_snippet("base", code, timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            "activity extraction timed out after "
            f"{timeout_seconds}s for {len(profile['activity_pages'])} classified activity pages"
        ) from exc
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()[:1200]
        raise RuntimeError(f"activity extraction failed: {err}")


def _production_smiles_ocr_options() -> dict:
    """Single source of truth for accepted production OCSR engines."""
    return {
        "engine": "decimer",
        "fallback": "",
    }
