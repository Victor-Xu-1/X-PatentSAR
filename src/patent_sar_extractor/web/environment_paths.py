"""Approved, operator-owned installation locations; never a browser file manager."""

from __future__ import annotations

import json
import os
import platform
import stat
import sys
from dataclasses import dataclass
from pathlib import Path

from .errors import WebError
from .files import SafeFiles, private_directory

MARKER = ".x-patentsar-environments.json"


@dataclass(frozen=True)
class ManagedStorage:
    allowed_root: Path
    default_root: Path
    operation_timeout_seconds: float = 7200

    @classmethod
    def from_environment(cls, state_root: Path) -> ManagedStorage:
        allowed = Path(
            os.environ.get("PATENTSAR_ENVIRONMENT_ALLOWED_ROOT")
            or str(state_root / "environments" / "managed")
        )
        selected = Path(
            os.environ.get("PATENTSAR_ENVIRONMENT_ROOT")
            or str(allowed / "x-patentsar-managed")
        )
        return cls(allowed, selected)

    def validate(self, value: str) -> Path:
        if (
            not value
            or "\\" in value
            or ":" in value
            or "\x00" in value
            or any(ord(c) < 32 for c in value)
        ):
            raise WebError(
                400,
                "environment_location",
                "Use a Linux path inside the approved WSL storage root; Windows/network paths are not installation prefixes.",
            )
        path = Path(value)
        allowed = self.allowed_root
        if (
            not path.is_absolute()
            or not allowed.is_absolute()
            or any(part in {".", ".."} for part in value.split("/"))
        ):
            raise WebError(
                400,
                "environment_location",
                "An absolute approved installation path is required.",
            )
        if path == allowed or not path.is_relative_to(allowed):
            raise WebError(
                400,
                "environment_location",
                "Installation must use a dedicated directory beneath the operator-approved root.",
            )
        for current in (path, *path.parents):
            if current.is_symlink():
                raise WebError(
                    400,
                    "environment_location",
                    "Installation paths cannot follow symbolic links.",
                )
            if current.exists() and current.is_relative_to(allowed):
                info = current.stat()
                if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
                    raise WebError(
                        400,
                        "environment_location",
                        "Installation directories must be operator-owned real directories.",
                    )
                if current == path and stat.S_IMODE(info.st_mode) & 0o077:
                    raise WebError(
                        400,
                        "environment_location",
                        "An existing installation prefix must be private (0700); its permissions were not changed.",
                    )
        if not path.resolve().is_relative_to(allowed.resolve()) or path.is_relative_to(
            Path("/mnt")
        ):
            raise WebError(
                400,
                "environment_location",
                "Installation must stay on the approved Linux filesystem, not a Windows mount.",
            )
        if path.exists() and any(path.iterdir()):
            try:
                marker = SafeFiles(path).read(MARKER, max_bytes=4096)
                verified = json.loads(marker) == {
                    "schema_version": 1,
                    "product": "X-PatentSAR",
                    "uid": os.getuid(),
                }
            except (WebError, ValueError, UnicodeError, RecursionError):
                verified = False
            if not verified:
                raise WebError(
                    409,
                    "environment_prefix_unknown",
                    "The selected directory is not a verified managed prefix; existing content was preserved.",
                )
        return path

    def prepare(self, value: str) -> Path:
        path = self.validate(value)
        root = private_directory(path)
        marker = root / MARKER
        payload = json.dumps(
            {"schema_version": 1, "product": "X-PatentSAR", "uid": os.getuid()}
        ).encode()
        try:
            descriptor = os.open(
                marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
            )
        except FileExistsError:
            self.validate(value)
        else:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
        return root

    def enabled_reason(self) -> str | None:
        if sys.platform != "linux" or platform.machine() != "x86_64":
            return (
                "Managed installation supports Linux/WSL x86_64 CPU environments only."
            )
        if not 0.05 <= self.operation_timeout_seconds <= 14400:
            return "The installation lifetime must be bounded by four hours."
        return None
