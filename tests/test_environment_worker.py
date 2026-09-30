"""Actual native worker/file protocol and owned-child cancellation regression."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from test_environment_recipes import RecipeFixture

from patent_sar_extractor.web.analysis_children import alive, read_child
from patent_sar_extractor.web.environment_models import EnvironmentComponent
from patent_sar_extractor.web.environment_specs import recipe_path
from patent_sar_extractor.workers.environment_commands import (
    install_environment,
    run_command,
)

WORKER = (
    Path(__file__).resolve().parents[1]
    / "src/patent_sar_extractor/workers/environment_install_worker.py"
)


class WorkerProtocolTests(RecipeFixture):
    def start(self):
        child = subprocess.Popen(
            [sys.executable, "-I", str(WORKER), "--plan", str(self.plan_file)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.addCleanup(self.stop, child)
        return child

    @staticmethod
    def stop(child):
        if child.poll() is None:
            child.kill()
        child.wait(timeout=3)
        if child.stdout:
            child.stdout.close()
        if child.stderr:
            child.stderr.close()

    def acknowledge(self, child, **changes):
        identity = read_child(child.pid)
        self.assertIsNotNone(identity)
        value = {
            "operation_id": self.identifier,
            "pid": child.pid,
            "start_ticks": identity.start_ticks,
            "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
            **changes,
        }
        (self.operation / "environment-owner.json").write_text(json.dumps(value))

    def test_real_worker_inspection_missing_component_with_owner_handshake(self):
        self.plan(requires_owner_ack=True)
        child = self.start()
        self.acknowledge(child)
        stdout, stderr = child.communicate(timeout=15)
        self.assertEqual(child.returncode, 0, stderr.decode())
        value = json.loads((self.operation / "environment-result.json").read_bytes())
        self.assertEqual(value["operation_id"], self.identifier)
        self.assertEqual(value["bindings"], {})
        card = EnvironmentComponent.model_validate(value["components"][0])
        self.assertEqual(card.status, "unconfigured")
        self.assertLess(len(stdout) + len(stderr), 4096)
        self.assertEqual(list(self.install.iterdir()), [self.marker])
        self.assertEqual(
            json.loads((self.operation / "environment-progress.json").read_bytes())[
                "completed_components"
            ],
            ["admet"],
        )

    def test_wrong_owner_or_cancel_before_ack_has_no_mutations_or_result(self):
        for action in ("wrong_owner", "cancel"):
            with self.subTest(action=action):
                self.plan(requires_owner_ack=True)
                child = self.start()
                if action == "wrong_owner":
                    self.acknowledge(child, start_ticks=0)
                else:
                    time.sleep(0.15)
                    child.terminate()
                stdout, stderr = child.communicate(timeout=5)
                self.assertNotEqual(child.returncode, 0)
                self.assertNotIn(b"Traceback", stderr)
                self.assertLess(len(stdout) + len(stderr), 1024)
                self.assertFalse((self.operation / "environment-result.json").exists())
                self.assertFalse(
                    (self.operation / "environment-progress.json").exists()
                )
                (self.operation / "environment-owner.json").unlink(missing_ok=True)

    def test_modified_uv_is_not_executed_by_read_only_inspection(self):
        untrusted = self.root / "uv"
        touched = self.root / "should-not-exist"
        untrusted.write_text(f"#!/bin/sh\ntouch {touched}\n")
        untrusted.chmod(0o700)
        bindings = {**self.payload["bindings"], "installer": str(untrusted)}
        self.plan(component_ids=["installer"], bindings=bindings)
        child = self.start()
        _, stderr = child.communicate(timeout=15)
        self.assertEqual(child.returncode, 0, stderr.decode())
        result = json.loads((self.operation / "environment-result.json").read_bytes())
        self.assertEqual(result["components"][0]["status"], "incompatible")
        self.assertEqual(result["bindings"], {})
        self.assertFalse(touched.exists())

    def test_real_worker_publishes_only_fixed_identity_bound_failure_after_ack(self):
        self.plan(requires_owner_ack=True)
        operator_file = self.root / "operator.txt"
        operator_file.write_text("preserve operator content")
        (self.operation / "environment-progress.json").symlink_to(operator_file)
        child = self.start()
        self.acknowledge(child)
        _, stderr = child.communicate(timeout=15)
        self.assertNotEqual(child.returncode, 0)
        value = json.loads((self.operation / "environment-failure.json").read_bytes())
        self.assertEqual(
            value,
            {
                "schema_version": 1,
                "operation_id": self.identifier,
                "code": "invalid_content",
            },
        )
        self.assertNotIn(b"Traceback", stderr)
        self.assertNotIn(str(operator_file).encode(), stderr)
        self.assertEqual(operator_file.read_text(), "preserve operator content")
        self.assertFalse((self.operation / "environment-result.json").exists())

    def test_installed_layout_probe_never_imports_host_scientific_packages(self):
        package_root = WORKER.parent.parent
        host_site = self.root / "host-python312/site-packages"
        own_package = host_site / "patent_sar_extractor"
        (own_package / "workers").mkdir(parents=True)
        for relative in (
            "__init__.py",
            "contracts.py",
            "workers/__init__.py",
            "workers/analysis_protocol.py",
            "workers/environment_files.py",
            "workers/environment_probe_worker.py",
        ):
            shutil.copyfile(package_root / relative, own_package / relative)
        (host_site / "numpy.py").write_text(
            "raise RuntimeError('foreign host native-extension environment imported')\n"
        )
        completed = subprocess.run(
            [
                sys.executable,
                "-I",
                str(own_package / "workers/environment_probe_worker.py"),
            ],
            input=json.dumps(
                {"role": "base", "base_recipe": str(recipe_path("base-runtime.json"))}
            ).encode(),
            capture_output=True,
            cwd=self.operation,
            timeout=30,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr.decode())
        value = json.loads(completed.stdout)
        self.assertTrue(value["ok"], (value, completed.stderr.decode()))
        self.assertTrue(all(check["ok"] for check in value["result"]["checks"]), value)
        self.assertNotIn(b"foreign host", completed.stderr)


class OwnedCommandTests(RecipeFixture):
    def test_timeout_and_cancel_stop_owned_detached_child_not_unrelated_process(self):
        script = self.root / "owned.py"
        pid_file = self.operation / "child.pid"
        script.write_text(
            "import subprocess, sys, time\nfrom pathlib import Path\n"
            "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], start_new_session=True)\n"
            "Path(sys.argv[1]).write_text(str(child.pid))\ntime.sleep(60)\n"
        )
        unrelated = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"]
        )
        self.addCleanup(WorkerProtocolTests.stop, unrelated)
        for mode in ("timeout", "cancel"):
            with self.subTest(mode=mode):
                cancel = threading.Event()
                timer = threading.Timer(0.6, cancel.set)
                if mode == "cancel":
                    timer.start()
                try:
                    with self.assertRaises(
                        TimeoutError if mode == "timeout" else InterruptedError
                    ):
                        run_command(
                            [sys.executable, str(script), str(pid_file)],
                            operation_dir=self.operation,
                            env=install_environment(self.cache, self.operation),
                            cancel=cancel,
                            timeout=0.6 if mode == "timeout" else 3,
                        )
                finally:
                    timer.cancel()
                    timer.join(timeout=1) if timer.ident else None
                child = read_child(int(pid_file.read_text()))
                self.assertTrue(child is None or not alive(child))
                self.assertIsNone(unrelated.poll())

    def test_output_bound_and_sanitized_proxy_environment(self):
        with self.assertRaises(RuntimeError):
            run_command(
                [
                    sys.executable,
                    "-c",
                    "import os; os.write(1, b'x' * (9 * 1024 * 1024))",
                ],
                operation_dir=self.operation,
                env=install_environment(self.cache, self.operation),
                cancel=threading.Event(),
                timeout=3,
            )
        env = install_environment(self.cache, self.operation)
        self.assertEqual(env["CUDA_VISIBLE_DEVICES"], "-1")
        self.assertNotIn("CONDA_PREFIX", env)
        self.assertNotIn("OPENAI_API_KEY", env)
