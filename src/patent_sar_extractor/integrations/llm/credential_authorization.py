"""Revocable GUI credentials and explicit renewal, separate from semantic policy."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING

import yaml  # type: ignore[import-untyped]
from yaml.events import (  # type: ignore[import-untyped]
    AliasEvent,
    CollectionEndEvent,
    CollectionStartEvent,
)
from yaml.nodes import MappingNode, SequenceNode  # type: ignore[import-untyped]

from .private_state import read_private, write_private

if TYPE_CHECKING:
    from .config import EvidenceResolutionConfig

GRANT_SCHEMA = {"name": "patentsar.api-job-authorization", "version": 1}
PROVIDER_FIELDS = ("endpoint", "model", "protocol", "response_mode")


def credential_digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def policy_digest(policy: EvidenceResolutionConfig) -> str:
    value = asdict(policy)
    for key in ("api_key", "cache_path", "authorization_file"):
        value.pop(key)
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _unique_yaml(node) -> None:
    if isinstance(node, MappingNode):
        keys = [
            key.value for key, _ in node.value if key.tag == "tag:yaml.org,2002:str"
        ]
        if len(keys) != len(node.value) or len(set(keys)) != len(keys):
            raise ValueError("Ambiguous authorization mapping")
        for _, child in node.value:
            _unique_yaml(child)
    elif isinstance(node, SequenceNode):
        for child in node.value:
            _unique_yaml(child)


def current_credential(policy: EvidenceResolutionConfig) -> str | None:
    """Read only the recorded private authority; no DNS, cache, key echo or write."""
    if not policy.authorization_file:
        return policy.api_key or None
    try:
        path = Path(policy.authorization_file)
        if not path.is_absolute() or any(p.is_symlink() for p in path.parents):
            return None
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.getuid()
                or info.st_mode & 0o077
                or info.st_nlink != 1
                or info.st_size > 32768
            ):
                return None
            content = stream.read(32769)
        depth = 0
        for count, event in enumerate(yaml.parse(content), 1):
            if (
                count > 4096
                or isinstance(event, AliasEvent)
                or getattr(event, "anchor", None)
            ):
                return None
            if isinstance(event, CollectionStartEvent):
                depth += 1
            elif isinstance(event, CollectionEndEvent):
                depth -= 1
            if depth > 16:
                return None
        _unique_yaml(yaml.compose(content))
        loaded = yaml.safe_load(content)
        if not isinstance(loaded, dict) or not isinstance(
            loaded.get("api_settings"), dict
        ):
            return None
        consent, provider = loaded.get("evidence_resolution", {}), loaded.get("llm", {})
        if not isinstance(consent, dict) or not isinstance(provider, dict):
            return None
        if (
            consent.get("data_consent") is not True
            or consent.get("mode") != policy.mode
        ):
            return None
        defaults = {"protocol": "openai-compatible", "response_mode": "json-schema"}
        if any(
            provider.get(key, defaults.get(key, "")) != getattr(policy, key)
            for key in PROVIDER_FIELDS
        ):
            return None
        key = provider.get("api_key")
        if (
            not isinstance(key, str)
            or not 1 <= len(key) <= 4096
            or key != key.strip()
            or any(ord(c) < 32 for c in key)
        ):
            return None
        return key
    except (
        OSError,
        ValueError,
        TypeError,
        AttributeError,
        yaml.YAMLError,
        RecursionError,
    ):
        return None


def grant_path(root: Path, job_id: str) -> Path:
    return root / f"{job_id}.authorization.json"


def authorized_key(
    root: Path,
    job_id: str,
    original: str,
    policy: EvidenceResolutionConfig,
    original_digest: str,
) -> str:
    expected = original_digest
    path = grant_path(root, job_id)
    if path.exists() or path.is_symlink():
        grant = read_private(path)
        if (
            set(grant)
            != {
                "schema",
                "job_id",
                "original_sha256",
                "policy_sha256",
                "credential_sha256",
                "settings_revision",
            }
            or grant["schema"] != GRANT_SCHEMA
            or grant["job_id"] != job_id
            or grant["original_sha256"] != original
            or grant["policy_sha256"] != policy_digest(policy)
            or type(grant["settings_revision"]) is not int
            or not 0 <= grant["settings_revision"] <= 2**53 - 1
        ):
            raise ValueError("Foreign API authorization grant")
        expected = grant["credential_sha256"]
    if (
        not isinstance(expected, str)
        or len(expected) != 64
        or any(c not in "0123456789abcdef" for c in expected)
    ):
        raise ValueError("Malformed credential reference")
    current = current_credential(policy)
    return current if current and credential_digest(current) == expected else ""


def renew_authorization(
    context, current: EvidenceResolutionConfig, revision: int
) -> None:
    """Explicit credential-only renewal. Never change a snapshot or its quota."""
    frozen = context.policy
    current.validate()
    if (
        frozen.mode == "off"
        or not frozen.data_consent
        or not frozen.authorization_file
        or frozen.authorization_file != current.authorization_file
        or policy_digest(frozen) != policy_digest(current)
        or current_credential(current) != current.api_key
        or type(revision) is not int
        or not 0 <= revision <= 2**53 - 1
    ):
        raise ValueError(
            "The task's API profile cannot be changed by credential renewal"
        )
    write_private(
        grant_path(context.root, context.job_id),
        {
            "schema": GRANT_SCHEMA,
            "job_id": context.job_id,
            "original_sha256": context.original_sha256,
            "policy_sha256": policy_digest(frozen),
            "credential_sha256": credential_digest(current.api_key),
            "settings_revision": revision,
        },
    )
