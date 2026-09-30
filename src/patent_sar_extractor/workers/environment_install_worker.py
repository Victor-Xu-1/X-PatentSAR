"""Native Python 3.12 owned worker; the parent alone persists/activates config."""

from __future__ import annotations

import argparse
import platform
import signal
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from patent_sar_extractor.workers.environment_files import atomic_json
from patent_sar_extractor.workers.environment_plan import (
    read_plan,
    wait_for_owner,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True, type=Path)
    args = parser.parse_args()
    cancel = threading.Event()
    signal.signal(signal.SIGTERM, lambda _sig, _frame: cancel.set())
    signal.signal(signal.SIGINT, lambda _sig, _frame: cancel.set())
    try:
        if (
            sys.version_info[:2] != (3, 12)
            or sys.platform != "linux"
            or platform.machine() != "x86_64"
        ):
            raise ValueError(
                "Managed environments require native Linux x86_64 Python 3.12"
            )
        plan = read_plan(args.plan)
        wait_for_owner(plan, cancel)
        # No SDK import or provision action can occur before persisted ownership.
        from patent_sar_extractor.web.environment_inspection import inspect_components
        from patent_sar_extractor.workers.environment_recipes import (
            EnvironmentProvisioner,
        )

        result = EnvironmentProvisioner(plan, cancel, inspect_components).execute()
        if cancel.is_set():
            raise InterruptedError("Operation cancelled before result publication")
        atomic_json(
            plan.operation_dir, "environment-result.json", result, limit=512 * 1024
        )
        return 0
    except Exception as exc:  # noqa: BLE001 - fail-closed process boundary; never expose upstream payloads
        # Paths, upstream errors, raw command output and tracebacks are private.
        print(
            f"Environment operation failed type={type(exc).__name__}; no success result published.",
            file=sys.stderr,
            flush=True,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
