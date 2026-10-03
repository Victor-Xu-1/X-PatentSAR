"""Native Python 3.12 owned worker; the parent alone persists/activates config."""

from __future__ import annotations

import argparse
import json
import platform
import runpy
import signal
import sys
import threading
from pathlib import Path

runpy.run_path(
    str(Path(__file__).resolve().parents[1] / "worker_bootstrap.py"),
    run_name="__main__",
)
from patent_sar_extractor.workers.environment_errors import failure_from_exception
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
    provisioner = None
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

        provisioner = EnvironmentProvisioner(plan, cancel, inspect_components)
        result = provisioner.execute()
        if cancel.is_set():
            raise InterruptedError("Operation cancelled before result publication")
        atomic_json(
            plan.operation_dir, "environment-result.json", result, limit=512 * 1024
        )
        return 0
    except Exception as exc:  # noqa: BLE001 - fail-closed process boundary; never expose upstream payloads
        # Paths, upstream errors, raw command output and tracebacks are private.
        error = failure_from_exception(exc)
        if provisioner is not None:
            try:
                atomic_json(
                    plan.operation_dir,
                    "environment-failure.json",
                    {
                        "schema_version": 1,
                        "operation_id": plan.operation_id,
                        "code": error.code,
                    },
                    limit=4096,
                )
                atomic_json(
                    plan.operation_dir,
                    "environment-progress.json",
                    {
                        "stage": f"失败 [{error.code}]: {error.message}",
                        "completed_components": provisioner.completed,
                    },
                    limit=64 * 1024,
                )
            except (OSError, ValueError):
                print(
                    "Environment failure progress could not be persisted.",
                    file=sys.stderr,
                )
        print(
            json.dumps(
                {
                    "environment_error": error.code,
                    "message": error.message,
                    "tail": error.tail,
                },
                ensure_ascii=True,
            ),
            file=sys.stderr,
            flush=True,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
