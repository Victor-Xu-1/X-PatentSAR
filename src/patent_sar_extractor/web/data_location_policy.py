"""Private native data prefixes with explicit workspace and purpose ownership."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .errors import WebError
from .files import SafeFiles, private_directory

MARKER = ".x-patentsar-storage.json"


@dataclass(frozen=True)
class DataLocationPolicy:
    state_root: Path
    allowed_root: Path

    @classmethod
    def from_environment(cls, state_root: Path) -> DataLocationPolicy:
        return cls(
            state_root,
            Path(os.environ.get("PATENTSAR_DATA_ALLOWED_ROOT") or state_root.parent),
        )

    def legacy_root(self, kind: str) -> Path:
        return self.state_root / ("uploads" if kind == "uploads" else "runs")

    def identity(self, kind: str) -> dict[str, object]:
        return {
            "schema_version": 1,
            "product": "X-PatentSAR",
            "uid": os.getuid(),
            "kind": kind,
            "workspace_sha256": hashlib.sha256(
                str(self.state_root).encode()
            ).hexdigest(),
        }

    def validate(self, kind: str, value: str) -> Path:
        try:
            return self._validate(kind, value)
        except OSError as error:
            raise WebError(
                409,
                "storage_unavailable",
                "The selected data location could not be inspected safely.",
            ) from error

    def _validate(self, kind: str, value: str) -> Path:
        if (
            kind not in {"uploads", "results"}
            or not value
            or len(value) > 4096
            or "\\" in value
            or ":" in value
            or value.startswith("//")
            or any(ord(char) < 32 or ord(char) == 127 for char in value)
            or any(part in {".", ".."} for part in value.split("/"))
        ):
            raise WebError(
                400,
                "storage_location",
                "Use an absolute native Linux data directory inside the approved root.",
            )
        path = Path(value)
        allowed = self.allowed_root
        legacy = path == self.legacy_root(kind)
        if (
            not path.is_absolute()
            or str(path) != value
            or not allowed.is_absolute()
            or allowed == Path("/")
            or path.is_relative_to(Path("/mnt"))
            or (
                not legacy
                and (
                    path == allowed
                    or not path.is_relative_to(allowed)
                    or path.is_relative_to(self.state_root)
                )
            )
        ):
            raise WebError(
                400,
                "storage_location",
                "Select a dedicated data directory beneath the approved native storage root, outside private workspace internals.",
            )
        for current in (path, *path.parents):
            if current.is_symlink():
                raise WebError(
                    400,
                    "storage_location",
                    "Data directories cannot follow symbolic links.",
                )
            if current.exists() and current.is_relative_to(allowed):
                info = current.stat()
                if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
                    raise WebError(
                        400,
                        "storage_location",
                        "Data directories must be operator-owned real directories.",
                    )
                if current == path and stat.S_IMODE(info.st_mode) & 0o077:
                    raise WebError(
                        400,
                        "storage_location",
                        "Existing data directories must be private (0700); permissions were not changed.",
                    )
        if path.exists() and any(path.iterdir()) and not legacy:
            try:
                valid = json.loads(
                    SafeFiles(path).read(MARKER, max_bytes=4096)
                ) == self.identity(kind)
            except (WebError, ValueError, UnicodeError, RecursionError):
                valid = False
            if not valid:
                raise WebError(
                    409,
                    "storage_prefix_unknown",
                    "The directory contains unowned data; existing files were preserved.",
                )
        return path

    def prepare(self, kind: str, value: str) -> Path:
        try:
            path = private_directory(self.validate(kind, value))
            if path != self.legacy_root(kind):
                try:
                    descriptor = os.open(
                        path / MARKER,
                        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                        0o600,
                    )
                except FileExistsError:
                    self.validate(kind, value)
                else:
                    with os.fdopen(descriptor, "wb") as stream:
                        stream.write(json.dumps(self.identity(kind)).encode())
                        stream.flush()
                        os.fsync(stream.fileno())
            descriptor, temporary = tempfile.mkstemp(prefix=".storage-probe-", dir=path)
            try:
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(b"X-PatentSAR storage check")
                    stream.flush()
                    os.fsync(stream.fileno())
            finally:
                Path(temporary).unlink()  # Only the new exclusive write probe.
        except OSError as error:
            raise WebError(
                409,
                "storage_unwritable",
                "The selected directory is not writable; previous settings remain active.",
            ) from error
        return path

    def validate_set(
        self, uploads: str, results: str, roots: tuple[tuple[str, str], ...]
    ) -> tuple[Path, Path]:
        selected = (
            self.validate("uploads", uploads),
            self.validate("results", results),
        )
        candidates = (("uploads", selected[0]), ("results", selected[1]))
        for kind, path in candidates:
            for other_kind, raw in (*roots, ("uploads", uploads), ("results", results)):
                other = Path(raw)
                if kind == other_kind and path == other:
                    continue
                if path.is_relative_to(other) or other.is_relative_to(path):
                    raise WebError(
                        400,
                        "storage_overlap",
                        "Upload and result locations must not overlap each other or prior managed locations.",
                    )
        return selected
