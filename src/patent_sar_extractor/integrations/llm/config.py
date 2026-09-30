"""
Operator-owned LLM/VLM configuration adapter.

Single source of truth:
1. Environment variables override everything.
2. Operator-owned YAML overlays override packaged defaults.
3. Hardcoded fallbacks are last-resort only.
"""

from __future__ import annotations

import os
import logging
from functools import lru_cache

from patent_sar_extractor.paths import config_files

LLM_CONFIG_PATHS = config_files("llm.yaml")
logger = logging.getLogger(__name__)

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
                loaded = yaml.safe_load(f) or {}
            if not isinstance(loaded, dict):
                continue
            for key, value in loaded.items():
                if isinstance(value, dict) and isinstance(merged.get(key), dict):
                    merged[key].update(value)
                else:
                    merged[key] = value
        return merged
    except ImportError:
        pass
    except Exception as exc:
        logger.warning("Unable to load YAML LLM configuration: %s", exc)
        return {}

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
        logger.warning("Unable to parse fallback LLM configuration: %s", exc)
        return {}
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
