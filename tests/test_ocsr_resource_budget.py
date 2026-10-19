"""Model headroom and owned-worker limits do not affect other applications."""

from __future__ import annotations

import json
import os
import resource
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from patent_sar_extractor.core.ocsr.resource_budget import (
    check_model_headroom,
    process_peak_resident_mb,
    resident_budget_mb,
    worker_resident_mb,
)
from patent_sar_extractor.core.ocsr.worker_process import (
    JsonLineWorker,
    WorkerProtocolError,
)


class OCSRResourceBudgetTests(unittest.TestCase):
    def test_real_exec_peak_excludes_the_larger_previous_address_space(self):
        child = """
import json, resource
from pathlib import Path
from patent_sar_extractor.core.ocsr.resource_budget import process_peak_resident_mb
peak = process_peak_resident_mb()
current = next(int(s.split()[1])/1024 for s in Path('/proc/self/status').read_text().splitlines() if s.startswith('VmHWM:'))
print(json.dumps({'reported_mb':peak,'kernel_mb':current,'inherited_mb':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024}))
"""
        sampler = (
            "import subprocess, sys; block=bytearray(96*1024*1024); block[::4096]=bytes([1])*len(block[::4096]); print(subprocess.check_output([sys.executable,'-c',"
            + repr(child)
            + "],text=True),end='')"
        )
        root = Path(__file__).resolve().parents[1] / "src"
        completed = subprocess.run(
            [sys.executable, "-c", sampler],
            env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "PYTHONPATH": str(root)},
            capture_output=True,
            text=True,
            timeout=15,
            check=True,
        )
        observed = json.loads(completed.stdout)
        self.assertLess(abs(observed["reported_mb"] - observed["kernel_mb"]), 2)
        self.assertGreater(observed["inherited_mb"], 80)
        self.assertGreater(observed["inherited_mb"], observed["reported_mb"] * 2)

    def test_missing_peak_fails_instead_of_falling_back_to_inherited_or_zero(self):
        with (
            patch.object(Path, "read_text", return_value="VmRSS: 2048 kB\n"),
            self.assertRaisesRegex(RuntimeError, "unavailable"),
        ):
            process_peak_resident_mb()
        for status in (
            "VmHWM: NaN kB\n",
            "VmHWM: 10 MB\n",
            "VmHWM: 1 kB\nVmHWM: 2 kB\n",
        ):
            with (
                self.subTest(status=status),
                patch.object(Path, "read_text", return_value=status),
                self.assertRaises(ValueError),
            ):
                process_peak_resident_mb()

    def test_native_reporters_measure_their_current_address_space_not_inherited_rusage(
        self,
    ):
        from patent_sar_extractor.core.ocsr.molscribe_model import PinnedMolScribeModel
        from patent_sar_extractor.core.ocsr.printed_model import PrintedDecimerModel

        # Linux retains the previous address space's high-water value in rusage
        # across exec. The actual current process VmHWM is a different quantity.
        status = Path("/proc/self/status").read_text()
        current_kb = next(
            int(line.split()[1])
            for line in status.splitlines()
            if line.startswith("VmHWM:")
        )
        with (
            patch.object(
                resource,
                "getrusage",
                return_value=SimpleNamespace(ru_maxrss=current_kb * 100),
            ),
            patch.object(Path, "read_text", return_value=status),
        ):
            for model in (PrintedDecimerModel, PinnedMolScribeModel):
                reporter = object.__new__(model)  # No SDK, model, image or inference.
                self.assertAlmostEqual(
                    reporter.peak_rss_mb, current_kb / 1024, places=2
                )

    def test_default_budget_and_invalid_bounds(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(resident_budget_mb(), 4096)
        for value in ("0", "2047", "16385", "bad"):
            with (
                self.subTest(value=value),
                patch.dict(os.environ, {"PATENTSAR_DECIMER_MAX_RSS_MB": value}),
                self.assertRaises(ValueError),
            ):
                resident_budget_mb()

    def test_low_headroom_fails_before_model_import(self):
        from patent_sar_extractor.resource_admission import ResourceAdmissionError

        with patch(
            "patent_sar_extractor.resource_admission.wait_for_memory",
            side_effect=ResourceAdmissionError("No model was loaded"),
        ) as admission:
            with self.assertRaisesRegex(RuntimeError, "No model was loaded"):
                check_model_headroom()
            admission.assert_called_once_with(3072)
        with patch(
            "patent_sar_extractor.resource_admission.wait_for_memory"
        ) as admission:
            check_model_headroom()
            admission.assert_called_once_with(3072)

    def test_owned_process_rss_and_exit_are_observable(self):
        self.assertGreater(worker_resident_mb(os.getpid()), 0)
        with patch("pathlib.Path.read_text", side_effect=FileNotFoundError):
            self.assertIsNone(worker_resident_mb(99999999))

    def test_receive_fails_when_owned_worker_exceeds_budget(self):
        from types import SimpleNamespace

        worker = JsonLineWorker.__new__(JsonLineWorker)
        worker.process = SimpleNamespace(pid=123)
        with (
            patch(
                "patent_sar_extractor.core.ocsr.worker_process.worker_resident_mb",
                return_value=4097,
            ),
            self.assertRaisesRegex(WorkerProtocolError, "memory budget"),
        ):
            worker.receive(1)
