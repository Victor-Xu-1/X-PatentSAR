"""
Operator-owned LLM/VLM configuration adapter.

Single source of truth:
1. Environment variables override everything.
2. Operator-owned YAML overlays override packaged defaults.
3. Hardcoded fallbacks are last-resort only.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

from patent_sar_extractor.paths import config_files

LLM_CONFIG_PATHS = config_files("llm.yaml")
logger = logging.getLogger(__name__)
_CONFIG_ERROR_KEY = "_configuration_error"

FALLBACKS = {
    "endpoint": "https://ark.cn-beijing.volces.com/api/coding/v3",
    "api_key": "",
    "model": "ark-code-latest",
    "timeout": 180,
    "max_workers": 4,
    "cache_path": "",
}


@lru_cache(maxsize=1)
def _load_yaml_config() -> dict:
    try:
        import yaml

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
                if isinstance(value, dict) and isinstance(merged.get(key), dict):
                    merged[key].update(value)
                else:
                    merged[key] = value
        return merged
    except ImportError:
        pass
    except Exception as exc:
        logger.warning("Unable to load YAML LLM configuration (%s)", type(exc).__name__)
        return {_CONFIG_ERROR_KEY: True}

    config: dict[str, object] = {}
    current_section = None
    try:
        for config_path in LLM_CONFIG_PATHS:
            if not config_path.is_file():
                continue
            with open(config_path, "r", encoding="utf-8") as f:
                for raw_line in f:
                    if not raw_line.strip() or raw_line.lstrip().startswith("#"):
                        continue
                    indent = len(raw_line) - len(raw_line.lstrip(" "))
                    line = raw_line.strip()
                    if line.endswith(":") and indent == 0:
                        current_section = line[:-1].strip()
                        config.setdefault(current_section, {})
                        continue
                    if ":" not in line:
                        continue
                    key, value = line.split(":", 1)
                    value = value.strip().strip('"').strip("'")
                    target = config[current_section] if current_section and isinstance(config.get(current_section), dict) else config
                    target[key.strip()] = value
    except Exception as exc:
        logger.warning("Unable to parse fallback LLM configuration (%s)", type(exc).__name__)
        return {_CONFIG_ERROR_KEY: True}
    return config


def _coerce_int(value, default: int) -> int:
    try:
        return int(str(value).strip())
    except Exception:
        return default


def _resolve(role: str, key: str, env_names: list[str], default):
    for env_name in env_names:
        env_value = os.environ.get(env_name)
        if env_value is not None and str(env_value).strip() != "":
            return env_value.strip() if isinstance(env_value, str) else env_value

    config = _load_yaml_config()
    role_cfg = config.get(role, {}) if isinstance(config.get(role), dict) else {}
    shared_cfg = config.get("shared", {}) if isinstance(config.get("shared"), dict) else {}

    if key in role_cfg and str(role_cfg[key]).strip() != "":
        return role_cfg[key]
    if key in shared_cfg and str(shared_cfg[key]).strip() != "":
        return shared_cfg[key]
    return default


def get_llm_config() -> dict:
    return {
        "endpoint": _resolve("llm", "endpoint", ["LLM_ENDPOINT"], FALLBACKS["endpoint"]),
        "api_key": _resolve("llm", "api_key", ["LLM_API_KEY"], FALLBACKS["api_key"]),
        "model": _resolve("llm", "model", ["LLM_MODEL"], FALLBACKS["model"]),
        "timeout": _coerce_int(_resolve("llm", "timeout", ["LLM_TIMEOUT"], FALLBACKS["timeout"]), FALLBACKS["timeout"]),
        "max_workers": _coerce_int(
            _resolve("llm", "max_workers", ["LLM_MAX_WORKERS"], FALLBACKS["max_workers"]),
            FALLBACKS["max_workers"],
        ),
        "cache_path": str(_resolve("llm", "cache_path", ["LLM_CACHE_PATH"], FALLBACKS["cache_path"])),
    }


def get_vlm_config() -> dict:
    llm = get_llm_config()
    return {
        "endpoint": _resolve("vlm", "endpoint", ["VLM_API_URL", "LLM_ENDPOINT"], llm["endpoint"]),
        "api_key": _resolve("vlm", "api_key", ["VLM_API_KEY", "LLM_API_KEY"], llm["api_key"]),
        "model": _resolve("vlm", "model", ["VLM_MODEL", "LLM_MODEL"], llm["model"]),
        "timeout": _coerce_int(_resolve("vlm", "timeout", ["VLM_TIMEOUT", "LLM_TIMEOUT"], llm["timeout"]), llm["timeout"]),
    }


def has_llm_key() -> bool:
    return bool(str(get_llm_config().get("api_key", "")).strip())


@dataclass(frozen=True)
class EvidenceResolutionConfig:
    """Optional disclosure policy; generic advisory settings never enable it."""

    mode: Literal["off", "on-error", "quality"] = "off"
    data_consent: bool = False
    endpoint: str = ""
    api_key: str = field(default="", repr=False)
    model: str = ""
    cache_path: str = ""
    timeout: int = 30
    retries: int = 0
    max_calls: int = 8
    max_input_chars: int = 12000
    max_output_chars: int = 8192
    max_tokens: int = 1024

    def validate(self) -> None:
        if self.mode not in {"off", "on-error", "quality"} or type(self.data_consent) is not bool:
            raise ValueError("Invalid evidence disclosure policy")
        for key, lower, upper in (
            ("timeout", 1, 45), ("retries", 0, 1), ("max_calls", 1, 8),
            ("max_input_chars", 1, 32768), ("max_output_chars", 1, 16384),
            ("max_tokens", 1, 2048),
        ):
            value = getattr(self, key)
            if type(value) is not int or not lower <= value <= upper:
                raise ValueError("Invalid evidence resource bound")
        if self.mode == "off" or not self.data_consent:
            return
        if any(
            not isinstance(value, str) or not value.strip() or len(value) > limit
            or any(ord(char) < 32 for char in value)
            for value, limit in ((self.endpoint, 2048), (self.model, 128), (self.api_key, 4096))
        ) or not isinstance(self.cache_path, str) or len(self.cache_path) > 2048:
            raise ValueError("Incomplete evidence provider configuration")
        endpoint = urlsplit(self.endpoint)
        if (
            endpoint.scheme != "https" or not endpoint.hostname
            or endpoint.username is not None or endpoint.password is not None
            or endpoint.query or endpoint.fragment
        ):
            raise ValueError("Invalid evidence provider endpoint")


def _evidence_option(key: str, default):
    loaded = _load_yaml_config()
    if loaded.get(_CONFIG_ERROR_KEY):
        raise ValueError("LLM configuration could not be read")
    env = os.environ.get(f"PATENTSAR_LLM_RESOLUTION_{key.upper()}")
    if env is not None:
        return env.strip()
    config = loaded.get("evidence_resolution", {})
    if not isinstance(config, dict):
        raise TypeError("Invalid evidence policy configuration")
    return config.get(key, default)


def get_evidence_resolution_config() -> EvidenceResolutionConfig:
    """Read an optional evidence_resolution section, with no enabling fallback."""
    defaults = EvidenceResolutionConfig()
    consent = _evidence_option("data_consent", False)
    if isinstance(consent, str) and consent in {"true", "false"}:
        consent = consent == "true"
    if type(consent) is not bool:
        raise ValueError("Explicit boolean data consent is required")
    values = {"mode": _evidence_option("mode", "off"), "data_consent": consent}
    for key in ("timeout", "retries", "max_calls", "max_input_chars", "max_output_chars", "max_tokens"):
        value = _evidence_option(key, getattr(defaults, key))
        if isinstance(value, str) and re.fullmatch(r"\d+", value):
            value = int(value)
        values[key] = value
    provider = (
        {
            key: _resolve("llm", key, [f"LLM_{key.upper()}"], "")
            for key in ("endpoint", "api_key", "model", "cache_path")
        }
        if values["mode"] != "off" and consent else {}
    )
    config = EvidenceResolutionConfig(
        **values,
        **{key: provider.get(key, "") for key in ("endpoint", "api_key", "model", "cache_path")},
    )
    config.validate()
    return config
