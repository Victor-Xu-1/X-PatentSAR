"""pipeline io: single application-layer policy authority."""

from __future__ import annotations

import logging
import os
import stat
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

from patent_sar_extractor.artifact_io import write_json_atomic as _write_json
from patent_sar_extractor.failures import write_failure_marker
from patent_sar_extractor.paths import config_files

logger = logging.getLogger("patent_sar_extractor")
WORKING_ROOT = Path.cwd()


def _worker_output_state(path: str) -> tuple[int, int, int] | None:
    """Freshness evidence for an owned producer, not a cache/QA authority."""
    try:
        info = Path(path).lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
        raise RuntimeError("Worker output is not a regular operator-owned file")
    return info.st_ino, info.st_mtime_ns, info.st_size


def _require_updated_worker_output(
    path: str, previous: tuple[int, int, int] | None
) -> None:
    current = _worker_output_state(path)
    if current is None or current == previous:
        raise RuntimeError(
            "Worker did not publish a current output; previous data is not accepted"
        )


@contextmanager
def _owned_worker_outputs(record: dict, paths: Sequence[str]) -> Iterator[None]:
    record["output_updated"] = False
    previous = [_worker_output_state(path) for path in paths]
    try:
        yield
    except BaseException:
        try:
            record["output_updated"] = all(
                (current := _worker_output_state(path)) is not None and current != prior
                for path, prior in zip(paths, previous, strict=True)
            )
        except (OSError, RuntimeError) as exc:
            logger.warning(
                "Failed worker output freshness unavailable (%s)", type(exc).__name__
            )
        raise
    else:
        for path, prior in zip(paths, previous, strict=True):
            _require_updated_worker_output(path, prior)
        record["output_updated"] = True


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
