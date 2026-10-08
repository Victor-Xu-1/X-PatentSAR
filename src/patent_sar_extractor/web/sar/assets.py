"""Owned atomic SAR assets below the existing configured upload/result roots."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

from ..errors import WebError
from ..files import SafeFiles, private_directory
from ..storage import encode
from ..workspace_locations import WorkspaceLocations

MAX_PACKET_BYTES = 32 * 1024 * 1024


def digest(value: object) -> str:
    return hashlib.sha256(encode(value).encode()).hexdigest()


def atomic_bytes(root: Path, filename: str, data: bytes) -> None:
    if (
        not re.fullmatch(r"[a-zA-Z0-9_.-]{1,100}", filename)
        or len(data) > MAX_PACKET_BYTES
    ):
        raise WebError(
            413, "sar_asset_limit", "SAR asset is invalid or exceeds its limit."
        )
    private_directory(root)
    fd, name = tempfile.mkstemp(prefix=".sar-", dir=root)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(name, root / filename)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def atomic_json(root: Path, filename: str, value: object) -> None:
    atomic_bytes(root, filename, encode(value).encode())


class SARAssets:
    def __init__(self, workspace_root: Path):
        self.workspace_root = workspace_root
        self.locations = WorkspaceLocations(workspace_root)
        self.owner = digest(["patentsar.sar-assets", str(workspace_root)])

    def area(self, kind: str) -> Path:
        parent = (
            self.locations.upload_root()
            if kind == "uploads"
            else self.locations.result_root()
        )
        root = parent / "sar-research"
        existed = root.exists() or root.is_symlink()
        private_directory(root)
        if not existed:
            atomic_json(root, "owner.json", {"owner": self.owner, "kind": kind})
        self.validate(root, kind)
        return root

    def validate(self, root: Path, kind: str) -> SafeFiles:
        if root.name != "sar-research" or root.parent not in self.locations.roots(kind):
            raise WebError(
                409, "sar_storage", "SAR assets are outside recorded storage roots."
            )
        self.locations.policy.validate(kind, str(root.parent))
        safe = SafeFiles(private_directory(root))
        marker = json.loads(safe.read("owner.json", max_bytes=1024))
        if marker != {"owner": self.owner, "kind": kind}:
            raise WebError(409, "sar_storage", "SAR asset ownership is not verified.")
        return safe

    def job_root(self, identifier: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{32}", identifier):
            raise WebError(422, "sar_identifier", "SAR task identifier is invalid.")
        return private_directory(self.area("results") / identifier)

    def job_files(self, raw: str, identifier: str) -> SafeFiles:
        path = Path(raw)
        if not path.is_absolute() or str(path) != raw or path.name != identifier:
            raise WebError(409, "sar_storage", "SAR task location is invalid.")
        self.validate(path.parent, "results")
        return SafeFiles(private_directory(path))
