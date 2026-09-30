"""Filesystem boundaries for packaged defaults and operator-owned state."""

from __future__ import annotations

import os
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parent
PACKAGE_IMPORT_ROOT = PACKAGE_ROOT.parent
PACKAGED_DEFAULTS_DIR = PACKAGE_ROOT / "defaults"


def _xdg_dir(env_name: str, fallback: Path) -> Path:
    configured = str(os.environ.get(env_name, "") or "").strip()
    return Path(configured).expanduser().resolve() if configured else fallback


def operator_config_dir() -> Path:
    configured = str(os.environ.get("PATENTSAR_CONFIG_DIR", "") or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    xdg_root = _xdg_dir("XDG_CONFIG_HOME", Path.home() / ".config")
    return xdg_root / "patent-sar-extractor"


def state_dir() -> Path:
    configured = str(os.environ.get("PATENTSAR_STATE_DIR", "") or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    xdg_root = _xdg_dir("XDG_STATE_HOME", Path.home() / ".local" / "state")
    return xdg_root / "patent-sar-extractor"


def config_files(name: str) -> tuple[Path, ...]:
    """Return packaged default followed by operator-owned overrides."""

    if not name or Path(name).name != name or not name.endswith(".yaml"):
        raise ValueError(f"invalid configuration filename: {name!r}")
    stem = name.removesuffix(".yaml")
    operator = operator_config_dir()
    return (
        PACKAGED_DEFAULTS_DIR / name,
        operator / name,
        operator / f"{stem}.local.yaml",
    )
