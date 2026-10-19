"""Verify the fixed ordinary-text model and reviewed SDK before any native import."""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import re
import sys
from importlib import metadata
from pathlib import Path, PurePosixPath

from patent_sar_extractor.core.ocsr.model_identity import _digest

RESOURCES = Path(__file__).resolve().parents[2] / "defaults/environments"


def recipe() -> dict:
    return json.loads((RESOURCES / "text-ocr-runtime.json").read_text(encoding="utf-8"))


def safe_file(path: Path) -> None:
    if not path.is_file() or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("Auxiliary text OCR content is missing or unsafe")


def model_files(root: Path, spec: dict) -> list[tuple[str, str]]:
    if not root.is_absolute():
        raise ValueError("Auxiliary text OCR requires an absolute model directory")
    result = []
    for item in spec["models"]:
        path = root / item["file"]
        safe_file(path)
        if path.stat().st_size != item["size"] or _digest(path) != item["sha256"]:
            raise ValueError(
                "Auxiliary text OCR model differs from the reviewed official files"
            )
        result.append((item["file"], item["sha256"]))
    return result


def sdk_manifest(resources: Path, spec: dict) -> dict:
    """Pinned generated-data provenance; no metadata/native SDK import occurs."""
    path = resources / "text-ocr-sdk.json"
    safe_file(path)
    raw = path.read_bytes()
    provenance = spec.get("sdk_inventory")
    if (
        not isinstance(provenance, dict)
        or set(provenance) != {"generator", "sha256"}
        or provenance["generator"] != "tools/build_text_ocr_resources.py"
        or len(raw) > 1024 * 1024
        or hashlib.sha256(raw).hexdigest() != provenance["sha256"]
    ):
        raise ValueError("Text OCR generated SDK inventory fingerprint differs")
    reviewed = json.loads(raw)
    if not isinstance(reviewed, dict) or set(reviewed) != {
        wheel["name"] for wheel in spec["sdk_wheels"]
    }:
        raise ValueError("Text OCR generated SDK distribution inventory differs")
    for wheel in spec["sdk_wheels"]:
        entries = reviewed[wheel["name"]]
        if not isinstance(entries, dict) or not 10 <= len(entries) <= 8192:
            raise ValueError("Text OCR SDK generated inventory is missing/unbounded")
        for name, digest in entries.items():
            relative = PurePosixPath(name)
            if (
                len(name) > 1024
                or any(ord(c) < 32 or ord(c) == 127 for c in name)
                or relative.as_posix() != name
                or not name.startswith(wheel["prefix"] + "/")
                or relative.is_absolute()
                or ".." in relative.parts
                or name.endswith(".pyc")
                or "\\" in name
                or not isinstance(digest, str)
                or not re.fullmatch(r"[a-f0-9]{64}", digest)
            ):
                raise ValueError("Text OCR SDK generated inventory is unsafe")
    return reviewed


def _sdk_inventory(spec: dict) -> list[tuple[str, str, str]]:
    reviewed = sdk_manifest(RESOURCES, spec)
    inventory = []
    for wheel in spec["sdk_wheels"]:
        distribution = metadata.distribution(wheel["name"])
        records = {
            row[0]: (row[1], row[2])
            for row in csv.reader(io.StringIO(distribution.read_text("RECORD") or ""))
            if len(row) == 3
            and row[0].startswith(wheel["prefix"] + "/")
            and not row[0].endswith(".pyc")
        }
        expected = reviewed[wheel["name"]]
        if not 10 <= len(records) <= 8192 or set(records) != set(expected):
            raise ValueError(
                "Auxiliary text OCR SDK inventory differs from the approved wheels"
            )
        for name, record in sorted(records.items()):
            path = Path(distribution.locate_file(name))
            safe_file(path)
            digest = _digest(path)
            declared = "sha256=" + base64.urlsafe_b64encode(
                bytes.fromhex(digest)
            ).decode().rstrip("=")
            if (
                record != (declared, str(path.stat().st_size))
                or digest != expected[name]
            ):
                raise ValueError(
                    "Auxiliary text OCR SDK differs from its reviewed source"
                )
            inventory.append((wheel["name"], name, digest))
    return inventory


def runtime_inventory(spec: dict) -> tuple[dict, list]:
    """Reviewed native code/version inventory, without loading a model."""
    if sys.version_info[:2] != (3, 10):
        raise ValueError("Auxiliary text OCR requires its isolated Python 3.10 runtime")
    versions = {name: metadata.version(name) for name in spec["distributions"]}
    if versions != spec["distributions"]:
        raise ValueError(
            "Auxiliary text OCR dependencies differ from the reviewed recipe"
        )
    return versions, _sdk_inventory(spec)


def text_identity(root: Path) -> dict:
    spec = recipe()
    models = model_files(root, spec)
    versions, sdk = runtime_inventory(spec)
    adapters = [
        (name, _digest(Path(__file__).parent / name))
        for name in (
            "identity.py",
            "protocol.py",
            "model.py",
            "worker.py",
            "request_stream.py",
        )
    ]
    adapters.extend(
        (name, _digest(Path(__file__).resolve().parents[2] / name))
        for name in (
            "worker_bootstrap.py",
            "worker_lifecycle.py",
            "workers/analysis_protocol.py",
            "core/ocsr/resource_budget.py",
        )
    )
    content = {
        "adapter_version": spec["adapter_version"],
        "model_name": spec["model_name"],
        "revision": spec["model_revision"],
        "versions": versions,
        "sdk": sdk,
        "models": models,
        "adapters": adapters,
        "python": sys.version.split()[0],
        "policy": {
            "device": "cpu",
            "threads": 2,
            "network": "denied",
            "input": "complete-RGB-row-to-BGR",
        },
    }
    fingerprint = hashlib.sha256(
        json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        "fingerprint": fingerprint,
        "model_name": spec["model_name"],
        "model_revision": spec["model_revision"],
        "adapter_version": spec["adapter_version"],
        "versions": versions,
        "device": "cpu",
        "model_directory": str(root),
    }
