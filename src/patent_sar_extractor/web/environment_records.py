"""The single bounded saved environment-plan/owned-workspace identity reader."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .environment_models import COMPONENT_IDS, MAX_COMPONENTS
from .errors import WebError
from .processes import RunSpec
from .storage import encode

MAX_PLAN_BYTES = 512 * 1024


def _native(value: object) -> bool:
    return bool(
        isinstance(value, str)
        and 1 <= len(value) <= 4096
        and Path(value).is_absolute()
        and Path(value) != Path("/")
        and not Path(value).is_relative_to("/mnt")
        and str(Path(value)) == value
        and "\\" not in value
        and ":" not in value
        and not any(ord(char) < 32 for char in value)
        and not any(part in {".", ".."} for part in value.split("/"))
    )


def environment_spec(
    row: dict[str, Any], state_root: Path
) -> tuple[RunSpec, dict[str, Any]]:
    """Only parse retained DB bytes; no plan file/model/location initialization."""
    try:
        identifier = row["id"]
        raw = row["spec"]
        components_raw = row["component_ids"]
        if (
            not isinstance(identifier, str)
            or re.fullmatch(r"[a-f0-9]{32}", identifier) is None
            or not isinstance(raw, str)
            or len(raw.encode()) > MAX_PLAN_BYTES
            or not isinstance(components_raw, str)
            or len(components_raw) > 1024
            or not _native(str(state_root))
        ):
            raise ValueError("Unbounded or foreign environment identity")
        value, components = json.loads(raw), json.loads(components_raw)
        if (
            not isinstance(value, dict)
            or type(value.get("schema_version")) is not int
            or value["schema_version"] != 1
            or value.get("operation_id") != identifier
            or not _native(row["install_root"])
            or value.get("install_root") != row["install_root"]
            or row["action"] not in {"inspect", "install"}
            or value.get("action") != row["action"]
            or value.get("component_ids") != components
            or not isinstance(components, list)
            or not 1 <= len(components) <= MAX_COMPONENTS
            or any(
                not isinstance(component, str) or component not in COMPONENT_IDS
                for component in components
            )
            or len(set(components)) != len(components)
        ):
            raise ValueError("Saved environment plan differs from its operation")
        if set(value) - {
            "schema_version",
            "operation_id",
            "action",
            "component_ids",
            "install_root",
            "bindings",
            "cache_root",
            "requires_owner_ack",
            "config_fingerprint",
            "source_key",
        }:
            raise ValueError("Unknown environment plan fields")
        if "bindings" in value:
            bindings = value["bindings"]
            # Earlier plans legitimately predate added component IDs. Keep
            # their known subset, never accept an unknown role or malformed path.
            if (
                not isinstance(bindings, dict)
                or not set(bindings) <= COMPONENT_IDS
                or any(
                    raw is not None and not _native(raw) for raw in bindings.values()
                )
            ):
                raise ValueError("Invalid saved environment bindings")
        root = state_root / "environments"
        if "cache_root" in value and value["cache_root"] != str(root / "downloads"):
            raise ValueError("Foreign environment cache")
        if "requires_owner_ack" in value and value["requires_owner_ack"] is not True:
            raise ValueError("Invalid environment handshake")
        for key in ("source_key", "config_fingerprint"):
            if key in value and (
                not isinstance(value[key], str)
                or re.fullmatch(r"[a-f0-9]{64}", value[key]) is None
            ):
                raise ValueError("Invalid saved plan fingerprint")
        output = root / "operations" / identifier
        if any(path.is_symlink() for path in (output, *output.parents)) or not (
            output.resolve().is_relative_to(root / "operations")
        ):
            raise ValueError(
                "Environment output must retain its no-link owned workspace"
            )
        digest = hashlib.sha256(encode(value).encode()).hexdigest()
        return RunSpec(
            identifier, "environment", "", str(output), "environment", digest
        ), value
    except (
        KeyError,
        ValueError,
        TypeError,
        RecursionError,
        UnicodeError,
        OSError,
    ) as error:
        raise WebError(
            409,
            "environment_record",
            "Saved environment operation/specification is invalid or foreign; no process or record was changed.",
        ) from error
