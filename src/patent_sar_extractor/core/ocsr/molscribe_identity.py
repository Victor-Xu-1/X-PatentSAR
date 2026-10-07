"""Content identity for the reviewed local rescue SDK; no model imports here."""

from __future__ import annotations

import base64
import csv
import hashlib
import importlib.metadata
import io
import json
import os
import sys
from pathlib import Path

from .model_identity import _digest


def rescue_recipe() -> dict:
    path = (
        Path(__file__).resolve().parents[2]
        / "defaults/environments/molscribe-runtime.json"
    )
    return json.loads(path.read_text(encoding="utf-8"))


def molscribe_identity(model_root: Path | None = None) -> dict:
    recipe = rescue_recipe()
    value = model_root or os.environ.get("PATENTSAR_MOLSCRIBE_MODEL_DIR")
    if not value:
        raise ValueError("Local rescue model directory is not configured")
    model = Path(value) / recipe["model"]["file"]
    if not model.is_file() or any(p.is_symlink() for p in (model, *model.parents)):
        raise ValueError("Local rescue model is missing or unsafe")
    if (
        model.stat().st_size != recipe["model"]["size"]
        or _digest(model) != recipe["model"]["sha256"]
    ):
        raise ValueError("Local rescue model checksum/size differs")
    versions = {
        name: importlib.metadata.version(name) for name in recipe["distributions"]
    }
    if versions != recipe["distributions"]:
        raise ValueError("Local rescue distributions differ from the reviewed recipe")
    distribution = importlib.metadata.distribution("MolScribe")
    records = {
        row[0]: (row[1], row[2])
        for row in csv.reader(io.StringIO(distribution.read_text("RECORD") or ""))
        if len(row) == 3
        and row[0].startswith("molscribe/")
        and not row[0].endswith(".pyc")
    }
    if not 10 <= len(records) <= 256:
        raise ValueError("Local rescue SDK inventory is missing or unbounded")
    reviewed_path = (
        Path(__file__).resolve().parents[2] / "defaults/environments/molscribe-sdk.json"
    )
    reviewed = json.loads(reviewed_path.read_text(encoding="utf-8"))
    if set(records) != set(reviewed):
        raise ValueError("Local rescue SDK inventory differs from the reviewed source")
    inventory = []
    for name, expected in sorted(records.items()):
        path = Path(distribution.locate_file(name))
        if not path.is_file() or any(p.is_symlink() for p in (path, *path.parents)):
            raise ValueError("Local rescue SDK contains missing or unsafe content")
        digest = _digest(path)
        declared = "sha256=" + base64.urlsafe_b64encode(
            bytes.fromhex(digest)
        ).decode().rstrip("=")
        if expected != (declared, str(path.stat().st_size)) or digest != reviewed[name]:
            raise ValueError("Local rescue SDK differs from its installed record")
        inventory.append((name, digest))
    adapter = [
        (name, _digest(Path(__file__).parent / name))
        for name in (
            "molscribe_identity.py",
            "molscribe_model.py",
            "wrapper_molscribe_batch.py",
        )
    ]
    content = {
        "adapter_version": "constrained-stereo-v1",
        "sdk": inventory,
        "versions": versions,
        "adapter": adapter,
        "model": recipe["model"]["sha256"],
        "python": sys.version.split()[0],
        "policy": {"device": "cpu", "threads": 2, "workers": 1},
    }
    fingerprint = hashlib.sha256(
        json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        "fingerprint": fingerprint,
        "versions": versions,
        "model_path": str(model),
        "adapter_version": "constrained-stereo-v1",
        "model_sha256": recipe["model"]["sha256"],
    }
