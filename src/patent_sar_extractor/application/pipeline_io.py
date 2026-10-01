"""pipeline io: single application-layer policy authority."""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

from patent_sar_extractor.artifact_io import write_json_atomic as _write_json
from patent_sar_extractor.failures import write_failure_marker
from patent_sar_extractor.paths import config_files

logger = logging.getLogger("patent_sar_extractor")
WORKING_ROOT = Path.cwd()


def _elapsed_since(start_time: float) -> float:
    return round(max(0.0, time.time() - start_time), 1)


def _strict_gates_enabled(args) -> bool:
    env_value = str(os.environ.get("PATENTSAR_STRICT_GATES", "") or "").strip().lower()
    if env_value in {"1", "true", "yes", "on"}:
        return True
    return bool(getattr(args, "strict_gates", False))


def _write_accuracy_failure_marker(
    output_dir: str, stage: str, errors: list[str]
) -> None:
    write_failure_marker(output_dir, stage, errors)


def _load_io_config() -> dict:
    config_paths = config_files("pipeline_io.yaml")
    try:
        import yaml

        merged = {}
        for config_path in config_paths:
            if not config_path.is_file():
                continue
            with open(config_path, "r", encoding="utf-8") as f:
                loaded = yaml.safe_load(f) or {}
            if isinstance(loaded, dict):
                merged.update(loaded)
        return merged
    except ImportError:
        cfg = {}
        for config_path in config_paths:
            if not config_path.is_file():
                continue
            with open(config_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or ":" not in line:
                        continue
                    key, val = line.split(":", 1)
                    cfg[key.strip()] = val.strip().strip('"').strip("'")
        return cfg


def _save_log(log: dict, base_dir: str):
    _write_json(os.path.join(base_dir, "pipeline_summary.json"), log)
