"""Operator-selected external runtimes and content-addressed model provenance."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
from dataclasses import dataclass
from pathlib import Path

from patent_sar_extractor.workers.analysis_protocol import (
    ADMET_BUNDLE_SHA256,
    ADMET_VERSION,
    ADMET_WHEEL_SHA256,
)

from .analysis_cache import cache_key
from .errors import WebError
from .files import SafeFiles


@dataclass(frozen=True)
class AnalysisSettings:
    admet_python: Path | None = None
    admet_model_dir: Path | None = None
    decimer_python: Path | None = None
    pystow_home: Path | None = None
    admet_timeout_seconds: float = 180
    decimer_timeout_seconds: float = 180

    def __post_init__(self) -> None:
        for value in (self.admet_timeout_seconds, self.decimer_timeout_seconds):
            if not math.isfinite(value) or not 0.05 <= value <= 180:
                raise WebError(
                    400,
                    "analysis_timeout",
                    "Analysis timeouts must be between 0.05 and 180 seconds.",
                )

    @classmethod
    def from_environment(cls) -> AnalysisSettings:
        from patent_sar_extractor.core.env_runner import (
            configured_model_environment,
            get_python,
        )

        models = configured_model_environment()

        def configured(name: str) -> Path | None:
            value = models.get(name, "").strip()
            return Path(value).expanduser() if value else None

        return cls(
            admet_python=configured("PATENTSAR_ADMET_PYTHON"),
            admet_model_dir=configured("PATENTSAR_ADMET_MODEL_DIR"),
            decimer_python=Path(get_python("decimer")),
            pystow_home=configured("PYSTOW_HOME"),
        )


@dataclass(frozen=True)
class Endpoint:
    key: str
    label: str
    unit: str
    kind: str
    probability: bool
    minimum: float | None = None
    maximum: float | None = None


@dataclass(frozen=True)
class ModelBundle:
    root: Path
    model_sha256: str
    endpoints: dict[str, Endpoint]


def executable(path: Path | None) -> Path:
    if (
        path is None
        or not path.is_absolute()
        or not path.is_file()
        or not os.access(path, os.X_OK)
    ):
        raise WebError(
            503,
            "analysis_environment_unavailable",
            "Configure an installed local analysis interpreter.",
        )
    return path


def interpreter_key(path: Path) -> str:
    """An environment change invalidates cache reuse even at the same interpreter path."""
    info = path.stat()
    sites = sorted(
        path.parent.parent.glob("lib/python*/site-packages/*.dist-info/METADATA")
    )
    if not sites or len(sites) > 500:
        raise WebError(
            503,
            "analysis_environment_unavailable",
            "Analysis environment metadata is missing or over its limit.",
        )
    items = []
    for item in sites:
        if item.is_symlink() or item.stat().st_size > 2 * 1024 * 1024:
            raise WebError(
                503,
                "analysis_environment_unavailable",
                "Analysis dependency metadata is unsafe.",
            )
        items.append((item.parent.name, hashlib.sha256(item.read_bytes()).hexdigest()))
    return cache_key([str(path), info.st_dev, info.st_ino, info.st_mtime_ns, items])


def admet_bundle(root: Path | None) -> ModelBundle:
    if root is None:
        raise WebError(
            503,
            "admet_models_unavailable",
            "Configure the verified local ADMET-AI 2.0.1 model bundle.",
        )
    try:
        safe = SafeFiles(root)
        manifest = json.loads(safe.read("manifest.json", max_bytes=64 * 1024))
        if (
            not isinstance(manifest, dict)
            or manifest.get("schema_version") != 1
            or manifest.get("version") != ADMET_VERSION
            or manifest.get("name") != "ADMET-AI"
            or manifest.get("wheel_sha256") != ADMET_WHEEL_SHA256
            or manifest.get("drugbank_reference") is not False
            or manifest.get("model_sha256") != ADMET_BUNDLE_SHA256
        ):
            raise ValueError("Unrecognized model provenance")
        entries = manifest["files"]
        expected = {
            "admet.csv",
            *(
                f"models/admet_{kind}/model_{i}.pt"
                for kind in ("classification", "regression")
                for i in range(5)
            ),
        }
        if (
            not isinstance(entries, list)
            or len(entries) != 11
            or any(
                not isinstance(e, dict) or set(e) != {"path", "sha256", "size"}
                for e in entries
            )
            or {e["path"] for e in entries} != expected
            or cache_key(entries) != ADMET_BUNDLE_SHA256
        ):
            raise ValueError("Invalid model file inventory")
        actual = {
            p.relative_to(root).as_posix() for p in (root / "models").rglob("*.pt")
        }
        if actual != expected - {"admet.csv"}:
            raise ValueError("Unexpected model file")
        for entry in entries:
            data = safe.read(entry["path"], max_bytes=32 * 1024 * 1024)
            if (
                len(data) != entry["size"]
                or hashlib.sha256(data).hexdigest() != entry["sha256"]
            ):
                raise ValueError("Model content changed")
        endpoints = _endpoints(safe.read("admet.csv", max_bytes=128 * 1024))
        return ModelBundle(root.resolve(), ADMET_BUNDLE_SHA256, endpoints)
    except (
        WebError,
        OSError,
        ValueError,
        KeyError,
        TypeError,
        UnicodeError,
        RecursionError,
    ) as exc:
        raise WebError(
            503,
            "admet_models_invalid",
            "Local ADMET models or metadata failed provenance validation.",
        ) from exc


def _endpoints(data: bytes) -> dict[str, Endpoint]:
    result = {}
    for row in csv.DictReader(io.StringIO(data.decode("utf-8"))):
        key, label = row["id"], row["name"]
        if not key or key in result or len(key) > 120 or not label or len(label) > 200:
            raise ValueError("Invalid endpoint metadata")
        probability = row["task_type"] == "classification"
        unit = "probability [0,1]" if probability else row["units"]
        unit = "dimensionless" if unit == "-" else unit
        kind = "descriptor" if row["category"] == "Physicochemical" else "prediction"
        minimum, maximum = float(row["minimum"]), float(row["maximum"])
        result[key] = Endpoint(
            key,
            label,
            unit,
            kind,
            probability,
            minimum if math.isfinite(minimum) else None,
            maximum if math.isfinite(maximum) else None,
        )
    if len(result) != 52:
        raise ValueError("ADMET-AI 2.0.1 endpoint inventory differs")
    return result


def decimer_model_key(root: Path | None) -> str:
    if root is None:
        raise WebError(
            503,
            "decimer_models_unavailable",
            "Configure PYSTOW_HOME with existing DECIMER weights; no automatic download is allowed.",
        )
    try:
        directory = root / "DECIMER-V2"
        safe = SafeFiles(directory)
        paths = sorted(p for p in directory.rglob("*") if p.is_file() or p.is_symlink())
        if not 1 <= len(paths) <= 64:
            raise ValueError("Missing or excessive model files")
        inventory: list[tuple[str, str]] = []
        for path in paths:
            relative = path.relative_to(directory).as_posix()
            digest = hashlib.sha256()
            with safe.open(relative, max_bytes=512 * 1024 * 1024) as stream:
                while data := stream.read(1024 * 1024):
                    digest.update(data)
            inventory.append((relative, digest.hexdigest()))
        if not any(p == "DECIMER_model/saved_model.pb" for p, _ in inventory):
            raise ValueError("Missing DECIMER model")
        return cache_key(inventory)
    except (WebError, OSError, ValueError) as exc:
        raise WebError(
            503,
            "decimer_models_unavailable",
            "Existing DECIMER model files are missing or unsafe; automatic download is disabled.",
        ) from exc


def child_environment(
    settings: AnalysisSettings, python: Path, temporary: Path
) -> dict[str, str]:
    """Allowlist rather than forwarding API/LLM keys, proxy credentials or Python paths."""
    env = {
        "PATH": f"{python.parent}:/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "CUDA_VISIBLE_DEVICES": "-1",
        "OMP_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1",
        "NUMEXPR_NUM_THREADS": "1",
        "VECLIB_MAXIMUM_THREADS": "1",
        "TF_NUM_INTRAOP_THREADS": "1",
        "TF_NUM_INTEROP_THREADS": "1",
        "TF_CPP_MIN_LOG_LEVEL": "3",
        "PATENTSAR_DECIMER_PERSISTENT": "0",
        "PYTHONUNBUFFERED": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "TMPDIR": str(temporary),
        "MPLCONFIGDIR": str(temporary / "matplotlib"),
        "XDG_CACHE_HOME": str(temporary / "cache"),
    }
    if settings.pystow_home:
        env["PYSTOW_HOME"] = str(settings.pystow_home)
    return env
