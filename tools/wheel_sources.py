"""One current-source inventory for fresh wheel staging and archive audit."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path, PurePosixPath
from typing import Protocol
from zipfile import ZipFile

PACKAGE = "patent_sar_extractor/"
STATIC = PACKAGE + "web/static/"


class _Readable(Protocol):
    def read(self, size: int = -1) -> bytes: ...


def _digest(stream: _Readable) -> bytes:
    value = hashlib.sha256()
    while block := stream.read(1024 * 1024):
        value.update(block)
    return value.digest()


def source_file(root: Path, relative: str) -> Path:
    path = PurePosixPath(relative)
    if path.is_absolute() or ".." in path.parts or "\\" in relative:
        raise ValueError("Unsafe source inventory path")
    candidate = root / relative
    if not candidate.resolve().is_relative_to(root.resolve()):
        raise ValueError("Source file escapes the repository")
    if any(
        part.is_symlink()
        for part in (candidate, *candidate.parents)
        if part != root.parent
    ):
        raise ValueError("Source inventory contains a symbolic link")
    if not candidate.is_file():
        raise ValueError(f"Source inventory file is missing: {relative}")
    return candidate


def package_files(root: Path, *, tracked: list[str] | None = None) -> dict[str, Path]:
    if tracked is None:
        raw = subprocess.check_output(
            ["git", "ls-files", "-z", "--", "src/patent_sar_extractor"], cwd=root
        )
        tracked = raw.decode("utf-8").strip("\0").split("\0")
    paths = {}
    for relative in tracked:
        if not relative.startswith("src/" + PACKAGE) or relative.startswith(
            "src/" + STATIC
        ):
            raise ValueError("Unexpected tracked package input")
        name = relative.removeprefix("src/")
        if Path(name).suffix not in {".py", ".yaml", ".json", ".txt"}:
            raise ValueError("Unexpected tracked package file type")
        paths[name] = source_file(root, relative)
    if PACKAGE + "contracts.py" not in paths:
        raise ValueError("Source inventory is missing product identity")
    marker_path = source_file(root, "src/" + STATIC + ".bundle.json")
    marker = json.loads(marker_path.read_text())
    if marker.get("generator") != "tools/build_frontend.py" or not isinstance(
        marker.get("files"), dict
    ):
        raise ValueError("Frontend source inventory has no verified manifest")
    paths[STATIC + ".bundle.json"] = marker_path
    for name, digest in marker["files"].items():
        path = source_file(root, "src/" + STATIC + name)
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError("Frontend source inventory checksum failed")
        paths[STATIC + name] = path
    return paths


def verify_package_files(archive: ZipFile, expected: dict[str, Path]) -> int:
    actual = {
        name
        for name in archive.namelist()
        if name.startswith(PACKAGE) and not name.endswith("/")
    }
    if actual != set(expected):
        raise ValueError(
            f"Wheel differs from current source inventory: extra={sorted(actual - set(expected))}; "
            f"missing={sorted(set(expected) - actual)}"
        )
    for name, path in expected.items():
        with path.open("rb") as source, archive.open(name) as member:
            if _digest(source) != _digest(member):
                raise ValueError(f"Wheel differs from current source bytes: {name}")
    return len(expected)
