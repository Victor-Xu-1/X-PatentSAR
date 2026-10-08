"""
Operator-owned external LLM API configuration adapter.

Single source of truth:
1. Environment variables override everything.
2. Operator-owned YAML overlays override packaged defaults.
3. Packaged defaults remain disabled with no provider or credential fallback.
"""

from __future__ import annotations

import logging
import os
import re
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml  # type: ignore[import-untyped]

from patent_sar_extractor.paths import config_files

from .external_api import validate_external_endpoint

LLM_CONFIG_PATHS = config_files("llm.yaml")
logger = logging.getLogger(__name__)
_CONFIG_ERROR_KEY = "_configuration_error"


def _load_yaml_config() -> dict:
    """Read current operator overlays; settings saves do not need a restart.

    A task uses a separate immutable private snapshot. A process-global YAML
    cache would otherwise let the web editor and next task disagree.
    """
    try:
        merged: dict[str, object] = {}
        for config_path in LLM_CONFIG_PATHS:
            if not config_path.is_file():
                continue
            with open(config_path, "r", encoding="utf-8") as f:
                loaded = yaml.safe_load(f)
            if loaded is None:
                loaded = {}
            if not isinstance(loaded, dict):
                logger.warning("LLM configuration must be a mapping")
                return {_CONFIG_ERROR_KEY: True}
            for key, value in loaded.items():
                existing = merged.get(key)
                if isinstance(value, dict) and isinstance(existing, dict):
                    existing.update(value)
                else:
                    merged[key] = value
        return merged
    except (OSError, ValueError, TypeError, yaml.YAMLError) as exc:
        logger.warning("Unable to load YAML LLM configuration (%s)", type(exc).__name__)
        return {_CONFIG_ERROR_KEY: True}


def _resolve(role: str, key: str, env_names: list[str], default):
    for env_name in env_names:
        env_value = os.environ.get(env_name)
        if env_value is not None and str(env_value).strip() != "":
            return env_value.strip() if isinstance(env_value, str) else env_value

    config = _load_yaml_config()
    role_cfg = config.get(role, {}) if isinstance(config.get(role), dict) else {}
    shared_cfg = (
        config.get("shared", {}) if isinstance(config.get("shared"), dict) else {}
    )

    if key in role_cfg:
        return role_cfg[key]
    if key in shared_cfg:
        return shared_cfg[key]
    return default


def get_llm_config() -> dict:
    """Compatibility accessor obeying the sole opt-in policy, never key-only."""
    policy = get_evidence_resolution_config()
    if policy.mode == "off" or not policy.data_consent:
        return {"endpoint": "", "api_key": "", "model": "", "cache_path": ""}
    return {
        key: getattr(policy, key)
        for key in (
            "endpoint",
            "api_key",
            "model",
            "cache_path",
            "timeout",
            "protocol",
            "response_mode",
        )
    }


@dataclass(frozen=True)
class EvidenceResolutionConfig:
    """Optional disclosure policy; generic advisory settings never enable it."""

    mode: Literal["off", "on-error", "quality"] = "off"
    data_consent: bool = False
    endpoint: str = ""
    api_key: str = field(default="", repr=False)
    model: str = ""
    protocol: Literal["openai-compatible", "anthropic", "gemini"] = "openai-compatible"
    response_mode: Literal["json-schema", "json-object", "prompt-only"] = "json-schema"
    cache_path: str = ""
    authorization_file: str = field(default="", repr=False)
    timeout: int = 30
    retries: int = 0
    max_calls: int = 8
    max_input_chars: int = 12000
    max_output_chars: int = 8192
    max_tokens: int = 1024

    def validate(self) -> None:
        if (
            self.mode not in {"off", "on-error", "quality"}
            or type(self.data_consent) is not bool
            or self.protocol not in {"openai-compatible", "anthropic", "gemini"}
            or self.response_mode not in {"json-schema", "json-object", "prompt-only"}
        ):
            raise ValueError("Invalid evidence disclosure policy")
        for key, lower, upper in (
            ("timeout", 1, 45),
            ("retries", 0, 1),
            ("max_calls", 1, 8),
            ("max_input_chars", 1, 32768),
            ("max_output_chars", 1, 16384),
            ("max_tokens", 1, 2048),
        ):
            value = getattr(self, key)
            if type(value) is not int or not lower <= value <= upper:
                raise ValueError("Invalid evidence resource bound")
        if self.mode == "off" or not self.data_consent:
            return
        if (
            any(
                not isinstance(value, str)
                or not value.strip()
                or len(value) > limit
                or any(ord(char) < 32 for char in value)
                for value, limit in (
                    (self.endpoint, 2048),
                    (self.model, 128),
                    (self.api_key, 4096),
                )
            )
            or not isinstance(self.cache_path, str)
            or len(self.cache_path) > 2048
        ):
            raise ValueError("Incomplete evidence provider configuration")
        validate_external_endpoint(self.endpoint)
        if self.protocol == "gemini" and not re.fullmatch(
            r"[A-Za-z0-9_.-]{1,128}", self.model.removeprefix("models/")
        ):
            raise ValueError("Invalid Gemini model name")


def _evidence_option(key: str, default):
    loaded = _load_yaml_config()
    if loaded.get(_CONFIG_ERROR_KEY):
        raise ValueError("LLM configuration could not be read")
    env = os.environ.get(f"PATENTSAR_LLM_RESOLUTION_{key.upper()}")
    if env is not None and env.strip():
        return env.strip()
    config = loaded.get("evidence_resolution", {})
    if not isinstance(config, dict):
        raise TypeError("Invalid evidence policy configuration")
    return config.get(key, default)


def snapshot_disclosure_allowed(policy: EvidenceResolutionConfig) -> bool:
    """A frozen policy is not permission to ignore a later GUI revocation.

    Semantics/quota remain immutable; withdrawing consent, disabling API use or
    clearing/rotating its credential prevents further external requests. Explicit
    operator ENV profiles are not GUI-managed and remain their operator's scope.
    """
    if not policy.authorization_file:
        return True
    try:
        path = Path(policy.authorization_file)
        if not path.is_absolute() or any(p.is_symlink() for p in path.parents):
            return False
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.getuid()
                or info.st_mode & 0o077
                or info.st_size > 32768
            ):
                return False
            loaded = yaml.safe_load(stream.read(32769))
        if not isinstance(loaded, dict) or not isinstance(
            loaded.get("api_settings"), dict
        ):
            return False
        current = loaded.get("evidence_resolution", {})
        provider = loaded.get("llm", {})
        if not isinstance(current, dict) or not isinstance(provider, dict):
            return False
    except (OSError, ValueError, TypeError, yaml.YAMLError):
        return False
    if current.get("data_consent") is not True or current.get("mode") not in {
        "on-error",
        "quality",
    }:
        return False
    return all(
        provider.get(key, "openai-compatible" if key == "protocol" else "")
        == getattr(policy, key)
        for key in ("endpoint", "model", "api_key", "protocol")
    )


def get_evidence_resolution_config() -> EvidenceResolutionConfig:
    """Read an optional evidence_resolution section, with no enabling fallback."""
    snapshot = os.environ.get("PATENTSAR_LLM_CONTEXT", "")
    if snapshot:
        from .job_context import read_context

        return read_context(snapshot).policy
    defaults = EvidenceResolutionConfig()
    consent = _evidence_option("data_consent", False)
    if isinstance(consent, str) and consent in {"true", "false"}:
        consent = consent == "true"
    if type(consent) is not bool:
        raise ValueError("Explicit boolean data consent is required")
    values = {
        "mode": _evidence_option("mode", "off"),
        "data_consent": consent,
        "protocol": _resolve("llm", "protocol", ["LLM_PROTOCOL"], "openai-compatible"),
        "response_mode": _resolve(
            "llm", "response_mode", ["LLM_RESPONSE_MODE"], "json-schema"
        ),
    }
    for key in (
        "timeout",
        "retries",
        "max_calls",
        "max_input_chars",
        "max_output_chars",
        "max_tokens",
    ):
        value = _evidence_option(key, getattr(defaults, key))
        if isinstance(value, str) and re.fullmatch(r"\d+", value):
            value = int(value)
        values[key] = value
    provider = (
        {
            key: _resolve("llm", key, [f"LLM_{key.upper()}"], "")
            for key in ("endpoint", "api_key", "model", "cache_path")
        }
        if values["mode"] != "off" and consent
        else {}
    )
    config = EvidenceResolutionConfig(
        **values,
        **{
            key: provider.get(key, "")
            for key in ("endpoint", "api_key", "model", "cache_path")
        },
    )
    loaded = _load_yaml_config()
    if isinstance(loaded.get("api_settings"), dict) and not any(
        os.environ.get(name, "").strip()
        for name in (
            "LLM_API_KEY",
            "LLM_ENDPOINT",
            "LLM_MODEL",
            "LLM_PROTOCOL",
            "PATENTSAR_LLM_RESOLUTION_MODE",
            "PATENTSAR_LLM_RESOLUTION_DATA_CONSENT",
        )
    ):
        from dataclasses import replace

        config = replace(config, authorization_file=str(LLM_CONFIG_PATHS[-1]))
    config.validate()
    return config
