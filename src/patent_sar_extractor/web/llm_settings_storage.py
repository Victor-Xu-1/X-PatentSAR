"""One bounded private operator YAML, no-link access and same-directory flock."""

from __future__ import annotations

import fcntl
import hashlib
import os
import secrets
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml
from yaml.events import AliasEvent, CollectionEndEvent, CollectionStartEvent
from yaml.nodes import MappingNode, ScalarNode, SequenceNode

from patent_sar_extractor.integrations.llm.config import EvidenceResolutionConfig

from .errors import WebError
from .llm_models import BOUND_NAMES, safe_text

MAX_YAML_BYTES = 32768
LOCAL_NAME = "llm.local.yaml"
_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


def unavailable() -> WebError:
    return WebError(409, "llm_configuration_unavailable", "LLM config is unavailable.")


def environment_overrides() -> dict[str, str]:
    return {
        key: value.strip()
        for key, value in os.environ.items()
        if key.startswith(("LLM_", "PATENTSAR_LLM_RESOLUTION_")) and value.strip()
    }


def policy_from_config(
    merged: dict[str, Any], env: dict[str, str]
) -> EvidenceResolutionConfig:
    sections = {
        key: merged.get(key, {}) for key in ("shared", "llm", "evidence_resolution")
    }
    if any(not isinstance(section, dict) for section in sections.values()):
        raise ValueError("Invalid LLM configuration section")
    provider = {**sections["shared"], **sections["llm"]}
    defaults = EvidenceResolutionConfig()
    values: dict[str, Any] = {}
    sizes = {
        "endpoint": 2048,
        "model": 128,
        "api_key": 4096,
        "cache_path": 2048,
        "protocol": 32,
        "response_mode": 32,
    }
    for key, size in sizes.items():
        value = env.get(f"LLM_{key.upper()}", provider.get(key, getattr(defaults, key)))
        values[key] = safe_text(value, size)
    for key in ("mode", "data_consent", *BOUND_NAMES):
        value = env.get(
            f"PATENTSAR_LLM_RESOLUTION_{key.upper()}",
            sections["evidence_resolution"].get(key, getattr(defaults, key)),
        )
        if key in BOUND_NAMES and isinstance(value, str) and value.isdecimal():
            value = int(value)
        if key == "data_consent" and value in ("true", "false"):
            value = value == "true"
        values[key] = value
    return EvidenceResolutionConfig(**values)


def _unique_keys(node: Any) -> None:
    if isinstance(node, MappingNode):
        keys = [
            key.value
            for key, _ in node.value
            if isinstance(key, ScalarNode) and key.tag == "tag:yaml.org,2002:str"
        ]
        if len(keys) != len(node.value) or len(set(keys)) != len(keys):
            raise ValueError("Ambiguous YAML mapping")
        for _, child in node.value:
            _unique_keys(child)
    elif isinstance(node, SequenceNode):
        for child in node.value:
            _unique_keys(child)


def _parse(payload: bytes) -> dict[str, Any]:
    text = payload.decode("utf-8")
    depth = 0
    for count, event in enumerate(yaml.parse(text), 1):
        if (
            count > 4096
            or isinstance(event, AliasEvent)
            or getattr(event, "anchor", None)
        ):
            raise ValueError("Excessive or aliased YAML")
        if isinstance(event, CollectionStartEvent):
            depth += 1
        elif isinstance(event, CollectionEndEvent):
            depth -= 1
        if depth > 16:
            raise ValueError("Excessive YAML nesting")
    _unique_keys(yaml.compose(text))
    loaded = yaml.safe_load(text)
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise TypeError("Configuration must be a mapping")
    return loaded


class LLMSettingsStorage:
    def __init__(self, config_dir: Path) -> None:
        if not config_dir.is_absolute() or ".." in config_dir.parts:
            raise unavailable()
        self.config_dir = config_dir

    @contextmanager
    def directory(
        self, *, create: bool = False, private: bool = True
    ) -> Iterator[int | None]:
        descriptor = os.open(self.config_dir.anchor, _DIRECTORY_FLAGS)
        try:
            for name in self.config_dir.parts[1:]:
                try:
                    child = os.open(name, _DIRECTORY_FLAGS, dir_fd=descriptor)
                except FileNotFoundError:
                    if not create:
                        yield None
                        return
                    try:
                        os.mkdir(name, mode=0o700, dir_fd=descriptor)
                        os.fsync(descriptor)
                    except FileExistsError:
                        pass
                    child = os.open(name, _DIRECTORY_FLAGS, dir_fd=descriptor)
                os.close(descriptor)
                descriptor = child
            info = os.fstat(descriptor)
            if private and (
                info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700
            ):
                raise unavailable()
            yield descriptor
        except (OSError, ValueError, UnicodeError, yaml.YAMLError, RecursionError):
            raise unavailable() from None
        finally:
            os.close(descriptor)

    @contextmanager
    def transaction(self) -> Iterator[int]:
        with self.directory(create=True) as descriptor:
            assert descriptor is not None
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise WebError(
                    409,
                    "llm_settings_busy",
                    "Another settings write is active; no request was replayed.",
                ) from None
            try:
                yield descriptor
            finally:
                fcntl.flock(descriptor, fcntl.LOCK_UN)

    @staticmethod
    def _check_file(descriptor: int, *, private: bool) -> None:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_YAML_BYTES:
            raise unavailable()
        if private and (
            info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_nlink != 1
        ):
            raise unavailable()

    @classmethod
    def read(cls, directory: int | None, name: str, *, private: bool = True) -> bytes:
        if directory is None:
            return b""
        try:
            descriptor = os.open(
                name,
                os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                dir_fd=directory,
            )
        except FileNotFoundError:
            return b""
        try:
            cls._check_file(descriptor, private=private)
            with os.fdopen(descriptor, "rb", closefd=False) as stream:
                payload = stream.read(MAX_YAML_BYTES + 1)
            cls._check_file(descriptor, private=private)
            if len(payload) > MAX_YAML_BYTES:
                raise unavailable()
            return payload
        finally:
            os.close(descriptor)

    def load(
        self, sources: tuple[Path, ...], *, directory: int | None = None
    ) -> tuple[dict[str, Any], dict[str, Any], str]:
        merged: dict[str, Any] = {}
        local: dict[str, Any] = {}
        fingerprint = hashlib.sha256()
        for index, path in enumerate(sources):
            if directory is not None and path.parent == self.config_dir:
                payload = self.read(directory, path.name)
            else:
                with LLMSettingsStorage(path.parent).directory(
                    private=index != 0
                ) as source_dir:
                    payload = self.read(source_dir, path.name, private=index != 0)
            fingerprint.update(str(path).encode("utf-8") + b"\0" + payload + b"\0")
            try:
                loaded = _parse(payload)
            except yaml.YAMLError:
                raise unavailable() from None
            if path == self.config_dir / LOCAL_NAME:
                local = loaded
            for key, value in loaded.items():
                if isinstance(value, dict) and isinstance(merged.get(key), dict):
                    merged[key] = {**merged[key], **value}
                else:
                    merged[key] = value
        return merged, local, fingerprint.hexdigest()

    def replace(
        self, directory: int, data: dict[str, Any], *, expected: dict[str, Any]
    ) -> None:
        payload = yaml.safe_dump(data, sort_keys=False, allow_unicode=True).encode()
        if len(payload) > MAX_YAML_BYTES:
            raise unavailable()
        previous = self.read(directory, LOCAL_NAME)
        if _parse(previous) != expected:
            raise WebError(
                409, "llm_settings_conflict", "Settings changed; reload before saving."
            )
        name = f".llm-{secrets.token_hex(16)}.tmp"
        descriptor = os.open(
            name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
            dir_fd=directory,
        )
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            if self.read(directory, LOCAL_NAME) != previous:
                raise WebError(
                    409,
                    "llm_settings_conflict",
                    "Settings changed; reload before saving.",
                )
            os.replace(name, LOCAL_NAME, src_dir_fd=directory, dst_dir_fd=directory)
            os.fsync(directory)
        finally:
            try:
                os.unlink(name, dir_fd=directory)
            except FileNotFoundError:
                pass

    def publish(
        self,
        directory: int,
        local: dict[str, Any],
        policy: EvidenceResolutionConfig,
        revision: int,
    ) -> None:
        """Preserve all unrelated operator sections and legacy provider fields."""
        data = deepcopy(local)
        data["llm"] = {
            **data.get("llm", {}),
            **{
                key: getattr(policy, key)
                for key in ("endpoint", "model", "api_key", "protocol", "response_mode")
            },
        }
        data["evidence_resolution"] = {
            **data.get("evidence_resolution", {}),
            "mode": policy.mode,
            "data_consent": policy.data_consent,
            **{name: getattr(policy, name) for name in BOUND_NAMES},
        }
        data["api_settings"] = {
            **data.get("api_settings", {}),
            "revision": revision,
            "last_test": None,
        }
        self.replace(directory, data, expected=local)
