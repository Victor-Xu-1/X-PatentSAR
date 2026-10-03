"""Verify the selected official printed model before loading code or pickle."""

from __future__ import annotations

import base64
import csv
import hashlib
import importlib.metadata
import io
import json
import os
from pathlib import Path

from patent_sar_extractor.contracts import DECIMER_ADAPTER_VERSION


def _digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def _verified_sdk_sources(distribution) -> tuple[Path, list[tuple[str, str]]]:
    sdk = Path(distribution.locate_file("DECIMER"))
    records = {
        row[0]: (row[1], row[2])
        for row in csv.reader(io.StringIO(distribution.read_text("RECORD") or ""))
        if len(row) == 3
    }
    inventory = []
    for name in ("pre_process.py", "utils.py"):
        path = sdk / name
        if (
            any(part.is_symlink() for part in (path, *path.parents))
            or not path.is_file()
        ):
            raise ValueError("DECIMER support code is missing or unsafe")
        digest = _digest(path)
        expected_hash = "sha256=" + base64.urlsafe_b64encode(
            bytes.fromhex(digest)
        ).decode().rstrip("=")
        if records.get(f"DECIMER/{name}") != (expected_hash, str(path.stat().st_size)):
            raise ValueError(
                "DECIMER support code differs from the hash-locked installed SDK"
            )
        inventory.append((name, digest))
    return sdk, inventory


def printed_model_identity(model_home: Path | None = None) -> dict:
    home = model_home or Path(os.environ.get("PYSTOW_HOME", str(Path.home() / ".data")))
    root = home / "DECIMER-V2"
    manifest = (
        Path(__file__).resolve().parents[2]
        / "defaults/environments/decimer-models.json"
    )
    selected = next(
        item
        for item in json.loads(manifest.read_text(encoding="utf-8"))["ocsrc"]
        if item["directory"] == "DECIMER_model"
    )
    inventory = []
    for entry in selected["files"]:
        path = root / entry["path"]
        if (
            any(part.is_symlink() for part in (path, *path.parents))
            or not path.is_file()
            or path.stat().st_size != entry["size"]
        ):
            raise ValueError(
                f"Official printed model is missing or has an unexpected size: {entry['path']}"
            )
        digest = _digest(path)
        if digest != entry["sha256"]:
            raise ValueError(
                f"Official printed model checksum mismatch: {entry['path']}"
            )
        inventory.append((entry["path"], digest))
    distribution = importlib.metadata.distribution("DECIMER")
    if distribution.version != "2.8.0":
        raise ValueError("This reviewed DECIMER adapter requires SDK 2.8.0")
    sdk, sdk_inventory = _verified_sdk_sources(distribution)
    versions = {
        name: importlib.metadata.version(name)
        for name in ("DECIMER", "tensorflow", "numpy", "Pillow", "efficientnet")
    }
    content = {
        "adapter_version": DECIMER_ADAPTER_VERSION,
        "adapter": [
            (name, _digest(Path(__file__).parent / name))
            for name in ("printed_model.py", "model_identity.py")
        ]
        + [
            (
                "worker_bootstrap.py",
                _digest(Path(__file__).resolve().parents[2] / "worker_bootstrap.py"),
            )
        ],
        "model": inventory,
        "sdk": sdk_inventory,
        "versions": versions,
        "execution_policy": {
            "gpu_enabled": os.environ.get("PATENTSAR_DECIMER_ENABLE_GPU", "0"),
            "cpu_threads": os.environ.get("PATENTSAR_DECIMER_CPU_THREADS", "2"),
        },
    }
    fingerprint = hashlib.sha256(
        json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        "fingerprint": fingerprint,
        "versions": versions,
        "model_directory": str(root / "DECIMER_model"),
        "sdk_directory": str(sdk),
        "adapter_version": DECIMER_ADAPTER_VERSION,
        "tokenizer_sha256": next(
            digest
            for name, digest in inventory
            if name.endswith("/tokenizer_SMILES.pkl")
        ),
    }
