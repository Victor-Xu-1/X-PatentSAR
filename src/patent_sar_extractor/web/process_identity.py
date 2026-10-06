"""Bounded process-record validation and conservative kernel presence proofs."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

MAX_IDENTITY_BYTES = 512 * 1024
MAX_DESCENDANTS = 256
REQUIRED = {"pid", "start_ticks", "boot_id", "pgid", "argv", "cwd", "executable"}
OPTIONAL = {"descendants", "phase"}


def valid_boot_id(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 36:
        return False
    try:
        parsed = uuid.UUID(value)
        return parsed.version == 4 and str(parsed) == value
    except ValueError:
        return False


def previous_kernel_boot(saved: object, current: object) -> bool:
    # A process cannot survive its kernel boot. An unknown string is not proof.
    return valid_boot_id(saved) and valid_boot_id(current) and saved != current


def _fields(raw: dict[str, Any]) -> None:
    for name in ("pid", "pgid", "start_ticks"):
        value = raw.get(name)
        maximum = 2**63 - 1 if name == "start_ticks" else 2**31 - 1
        if type(value) is not int or value < 1 or value > maximum:
            raise ValueError("Invalid process counters")
    for name in ("cwd", "executable"):
        value = raw.get(name)
        if (
            not isinstance(value, str)
            or not 1 <= len(value) <= 4096
            or "\x00" in value
            or not Path(value).is_absolute()
        ):
            raise ValueError("Invalid process location")
    argv = raw.get("argv")
    if (
        not isinstance(argv, list)
        or not 1 <= len(argv) <= 256
        or any(
            not isinstance(item, str) or len(item) > 8192 or "\x00" in item
            for item in argv
        )
        or sum(map(len, argv)) > 65536
    ):
        raise ValueError("Invalid process command")


def validate_identity(raw: object) -> dict[str, Any]:
    if (
        not isinstance(raw, dict)
        or not REQUIRED <= raw.keys()
        or raw.keys() - REQUIRED - OPTIONAL
    ):
        raise ValueError("Invalid process record")
    _fields(raw)
    if (
        raw["pid"] != raw["pgid"]
        or not valid_boot_id(raw["boot_id"])
        or raw.get("phase", "extract") not in {"extract", "admet"}
    ):
        raise ValueError("Invalid process leader or boot")
    descendants = raw.get("descendants", [])
    if not isinstance(descendants, list) or len(descendants) > MAX_DESCENDANTS:
        raise ValueError("Invalid process descendants")
    seen = {raw["pid"]}
    for item in descendants:
        if not isinstance(item, dict) or set(item) != {
            "pid",
            "ppid",
            "pgid",
            "start_ticks",
            "state",
            "argv",
            "cwd",
            "executable",
        }:
            raise ValueError("Invalid descendant record")
        _fields(item)
        if (
            type(item["ppid"]) is not int
            or not 0 <= item["ppid"] <= 2**31 - 1
            or not isinstance(item["state"], str)
            or len(item["state"]) != 1
            or item["pid"] in seen
        ):
            raise ValueError("Invalid descendant identity")
        seen.add(item["pid"])
    return raw


def process_present(pid: int) -> bool:
    """Unknown/permission-denied is present, not a claim that cleanup succeeded."""
    try:
        root = Path("/proc") / str(pid)
        root.stat()
        fields = (root / "stat").read_text().rsplit(")", 1)[1].split()
        return fields[0] not in {"Z", "X", "x"}
    except FileNotFoundError:
        return False
    except (OSError, ValueError, IndexError):
        return True
