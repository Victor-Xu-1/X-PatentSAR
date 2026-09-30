"""Transactional publication into the existing operator runtime configuration."""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml

from patent_sar_extractor.core.env_runner import get_python
from patent_sar_extractor.paths import operator_config_dir

from .analysis_runtime import AnalysisSettings
from .errors import WebError
from .files import SafeFiles

CONFIG_KEYS = {
    "installer": ("environment_installer",),
    "base": ("base", "smiles_engine", "pymupdf"),
    "decimer": ("decimer",),
    "decimer-models": ("decimer_models",),
    "admet": ("admet",),
    "admet-models": ("admet_models",),
}


class EnvironmentConfig:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or operator_config_dir()
        self.name = "env_paths.local.yaml"

    def content(self) -> bytes:
        if not self.root.exists() or not (self.root / self.name).exists():
            return b""
        path = self.root / self.name
        info = path.lstat()
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_mode & 0o022
        ):
            raise WebError(
                409,
                "environment_configuration",
                "Runtime configuration must be an operator-owned non-writable-by-others regular file.",
            )
        return SafeFiles(self.root).read(self.name, max_bytes=65536)

    def fingerprint(self) -> str:
        return hashlib.sha256(self.content()).hexdigest()

    def loaded(self) -> dict[str, Any]:
        value = yaml.safe_load(self.content()) or {}
        if not isinstance(value, dict):
            raise WebError(
                409,
                "environment_configuration",
                "Runtime configuration must be a mapping.",
            )
        return value

    def bindings(self, analysis: AnalysisSettings) -> dict[str, str | None]:
        def executable(value: str | Path | None) -> str | None:
            if not value:
                return None
            text = str(value)
            return text if Path(text).is_absolute() else shutil.which(text)

        loaded = self.loaded()
        return {
            "installer": executable(
                os.environ.get("PATENTSAR_ENVIRONMENT_UV")
                or loaded.get("environment_installer")
            ),
            "base": executable(get_python("base") or sys.executable),
            "decimer": executable(get_python("decimer")),
            "decimer-models": str(analysis.pystow_home)
            if analysis.pystow_home
            else None,
            "admet": str(analysis.admet_python) if analysis.admet_python else None,
            "admet-models": str(analysis.admet_model_dir)
            if analysis.admet_model_dir
            else None,
        }

    def publish(
        self,
        operation_id: str,
        expected_fingerprint: str,
        bindings: dict[str, str],
        *,
        additional: dict[str, str] | None = None,
    ) -> AnalysisSettings:
        if self.fingerprint() != expected_fingerprint:
            raise WebError(
                409,
                "environment_configuration_changed",
                "Runtime configuration changed during installation; verified environments were preserved but not activated. Refresh and configure again.",
            )
        loaded = self.loaded()
        for component, location in bindings.items():
            if (
                component not in CONFIG_KEYS
                or not Path(location).is_absolute()
                or "\x00" in location
            ):
                raise WebError(
                    409,
                    "environment_configuration",
                    "Only verified component bindings can be published.",
                )
            for key in CONFIG_KEYS[component]:
                loaded[key] = location
        for key, value in (additional or {}).items():
            if key != "decimer_segmentation_models" or not Path(value).is_absolute():
                raise WebError(
                    409,
                    "environment_configuration",
                    "Additional runtime paths are not allowed.",
                )
            loaded[key] = value
        loaded["_managed_environment_operation"] = operation_id
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.root.is_symlink() or self.root.stat().st_uid != os.getuid():
            raise WebError(
                409,
                "environment_configuration",
                "Runtime configuration must remain operator-owned.",
            )
        previous = self.content()
        backup_root = self.root / ".environment-backups"
        backup_root.mkdir(mode=0o700, exist_ok=True)
        if (
            backup_root.is_symlink()
            or backup_root.stat().st_uid != os.getuid()
            or backup_root.stat().st_mode & 0o077
        ):
            raise WebError(
                409,
                "environment_configuration",
                "Configuration backup storage is unsafe.",
            )
        if (
            not operation_id
            or not all(c in "0123456789abcdef" for c in operation_id)
            or len(operation_id) != 32
        ):
            raise WebError(
                409,
                "environment_configuration",
                "Configuration operation identity is invalid.",
            )
        backup = backup_root / (operation_id + ".yaml")
        try:
            descriptor = os.open(
                backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
            )
        except FileExistsError:
            if SafeFiles(backup_root).read(backup.name, max_bytes=65536) != previous:
                raise WebError(
                    409,
                    "environment_configuration",
                    "A different configuration backup already exists.",
                )
        else:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(previous)
                stream.flush()
                os.fsync(stream.fileno())
        descriptor, temporary = tempfile.mkstemp(
            prefix=".environment-config-", dir=self.root
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                yaml.safe_dump(loaded, stream, allow_unicode=True, sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
            if self.fingerprint() != expected_fingerprint:
                raise WebError(
                    409,
                    "environment_configuration_changed",
                    "Runtime configuration changed before publication; no operator changes were overwritten.",
                )
            os.replace(temporary, self.root / self.name)
            directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if Path(temporary).exists():
                Path(temporary).unlink()
        return AnalysisSettings.from_environment()
