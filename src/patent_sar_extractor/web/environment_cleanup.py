"""Read-only terminal cleanup proofs; never stop processes or erase identity."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .environment_process import environment_command
from .environment_records import environment_spec
from .errors import WebError
from .history_storage import TERMINAL
from .process_identity import (
    MAX_IDENTITY_BYTES,
    previous_kernel_boot,
    process_present,
    valid_boot_id,
    validate_identity,
)


def _current_boot() -> str:
    return Path("/proc/sys/kernel/random/boot_id").read_text().strip()


def environment_cleanup_block(
    row: dict[str, Any],
    state_root: Path,
    *,
    python: str | None = None,
    package_root: Path | None = None,
) -> str | None:
    """None proves terminal/no producer, prior valid kernel, or every saved PID absent.

    Optional runtime paths are trusted operator inputs for an idle/deploy check,
    never taken from a request or inferred from the saved untrusted command.
    A live/reused PID, unknown kernel/presence, malformed or foreign proof blocks.
    """
    if row.get("status") not in TERMINAL:
        return "Only terminal environment records can be removed; finish or cancel the active operation first."
    raw = row.get("identity")
    if raw is None:
        return None
    try:
        if not isinstance(raw, str) or len(raw.encode()) > MAX_IDENTITY_BYTES:
            raise ValueError("Unbounded process identity")
        identity = validate_identity(json.loads(raw))
        spec, _ = environment_spec(row, state_root)
        expected = environment_command(spec, python=python, package_root=package_root)
        if (
            identity["argv"] != expected
            or identity["cwd"] != spec.output_dir
            or identity["executable"] != str(Path(expected[0]).resolve())
            or identity.get("phase", "extract") != "extract"
        ):
            raise ValueError(
                "Environment ownership differs from the exact saved workspace/command"
            )
        current = _current_boot()
        if previous_kernel_boot(identity["boot_id"], current):
            return None  # Every old-kernel process is gone; do not inspect reused current PIDs.
        if not valid_boot_id(current) or current != identity["boot_id"]:
            raise ValueError("Unknown kernel identity")
        if any(
            process_present(pid)
            for pid in [
                identity["pid"],
                *(item["pid"] for item in identity.get("descendants", [])),
            ]
        ):
            return "An environment worker/descendant PID is live, reused or unverifiable; retained ownership must remain visible until absence is proved."
        return None
    except (
        WebError,
        ValueError,
        TypeError,
        KeyError,
        OSError,
        RecursionError,
        UnicodeError,
    ):
        return "Retained environment ownership is malformed, foreign or cannot be verified read-only; the original identity and forensic records were preserved."
