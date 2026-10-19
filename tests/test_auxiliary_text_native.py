"""Explicit opt-in native boundary checks, using only generated text images."""

import json
import os
import select
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

import fitz
import numpy as np

from patent_sar_extractor.core.activity_header_layout import discover_header_layout
from patent_sar_extractor.core.activity_header_observation import refine_scanned_header
from patent_sar_extractor.core.cell_header_proof import physical_header_valid
from patent_sar_extractor.core.ocsr.worker_process import WorkerProtocolError
from patent_sar_extractor.core.text_ocr.cell_capture import refine_text_pair
from patent_sar_extractor.core.text_ocr.cell_proof import replay_auxiliary_cell
from patent_sar_extractor.core.text_ocr.process import TextOCRCancelled
from patent_sar_extractor.core.text_ocr.runtime import AuxiliaryTextRuntime
from tests import test_auxiliary_cell_evidence as cell_fixture
from tests import test_auxiliary_header_discovery as layout_fixture

PYTHON = os.environ.get("PATENTSAR_TEST_TEXT_OCR_PYTHON")
MODELS = os.environ.get("PATENTSAR_TEST_TEXT_OCR_MODELS")


def native_orphan_owner(python, models, workspace):
    """Only the synthetic test starts this owner; no product/service control."""
    with AuxiliaryTextRuntime(Path(python), Path(models), Path(workspace)) as reader:
        reader.observe(original_row("BRD9"), timeout=60)
        print(json.dumps({"pid": reader.worker_process.pid}), flush=True)
        sys.stdin.read()


def original_row(text):
    with fitz.open() as document:
        page = document.new_page(width=190, height=32)
        page.insert_text((6, 23), text, fontsize=18, fontname="hebo")
        pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
        return np.frombuffer(pixmap.samples, np.uint8).reshape(
            pixmap.height, pixmap.width, 3
        )


@unittest.skipUnless(
    PYTHON and MODELS, "Explicit isolated text OCR runtime/model required"
)
class NativeAuxiliaryTextTests(unittest.TestCase):
    def test_actual_model_cannot_outlive_its_abruptly_killed_owner(self):
        from patent_sar_extractor.web.analysis_children import alive, read_child, send

        with tempfile.TemporaryDirectory() as temporary:
            caller = subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    "import sys; from tests.test_auxiliary_text_native import native_orphan_owner; native_orphan_owner(*sys.argv[1:])",
                    PYTHON,
                    MODELS,
                    temporary,
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            child = None
            try:
                self.assertTrue(
                    select.select([caller.stdout], [], [], 45)[0],
                    "Synthetic owner did not finish model startup",
                )
                packet = json.loads(caller.stdout.readline())
                child = read_child(packet["pid"])
                self.assertIsNotNone(child)
                self.assertEqual(child.parent, caller.pid)
                caller.kill()  # This Popen only, never the application or WSL.
                caller.communicate(timeout=2)
                deadline = time.monotonic() + 2
                while alive(child) and time.monotonic() < deadline:
                    time.sleep(0.02)
                self.assertFalse(
                    alive(child), "The loaded native text model survived its owner"
                )
            finally:
                if caller.poll() is None:
                    caller.kill()
                caller.communicate(timeout=2)
                if child is not None and alive(child):
                    send(
                        child, signal.SIGKILL
                    )  # Exact captured start-tick/pidfd ownership.

    def test_native_missing_layout_is_located_then_final_header_is_independently_checked(
        self,
    ):
        fixture = layout_fixture.AuxiliaryHeaderDiscoveryTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        with (
            tempfile.TemporaryDirectory() as temporary,
            AuxiliaryTextRuntime(Path(PYTHON), Path(MODELS), Path(temporary)) as reader,
        ):
            with fixture.observations(reader):
                layout = discover_header_layout(
                    fixture.page, fixture.region, (0, 20, 340, 210), 3
                )
                self.assertIsNotNone(layout.schema, str(layout.observations))
                result = refine_scanned_header(fixture.page, fixture.region, None)
            self.assertIsNotNone(result, reader.last_diagnostic)
            self.assertEqual(
                result.header_resolution["status"], "observed_header_consensus"
            )
            self.assertEqual(result.raw_headers, ("Compound", "IC50 (nM)"))

    def test_native_auxiliary_cell_retains_and_replays_both_original_views(self):
        fixture = cell_fixture.AuxiliaryCellEvidenceTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        with (
            tempfile.TemporaryDirectory() as temporary,
            AuxiliaryTextRuntime(Path(PYTHON), Path(MODELS), Path(temporary)) as reader,
        ):
            pair = refine_text_pair(fixture.images, fixture.primaries, reader)
            self.assertIsNotNone(pair, reader.last_diagnostic)
            for reading in pair:
                self.assertEqual(reading["text"], "HTRF\nEC50")
                self.assertTrue(physical_header_valid(reading))
                self.assertTrue(replay_auxiliary_cell(reading, fixture.page))

    def test_offline_owned_process_reads_differing_rows_and_closes(self):
        with tempfile.TemporaryDirectory() as temporary:
            with AuxiliaryTextRuntime(
                Path(PYTHON), Path(MODELS), Path(temporary)
            ) as reader:
                for text in ("HTRF", "Compound 27B", "0.125 nM"):
                    row = original_row(text)
                    try:
                        result = reader.observe(row, timeout=60)
                    except (
                        WorkerProtocolError,
                        OSError,
                        ValueError,
                        TimeoutError,
                    ) as error:
                        self.fail(f"{error}: {reader.last_diagnostic}")
                    self.assertEqual(result["text"], text)
                    self.assertEqual(result["device"], "cpu")
                    self.assertEqual(result["confidence_kind"], "uncalibrated_model")
                    self.assertLessEqual(result["peak_rss_mb"], 1024)
                    self.assertNotIn("accepted", result)
                    self.assertTrue(reader.observe(row)["cache_hit"])
                process = reader.worker_process
                root = reader.root
            self.assertIsNotNone(process.poll())
            self.assertFalse(root.exists())

    def test_cancel_before_a_later_request_releases_loaded_native_model(self):
        cancel = threading.Event()
        with (
            tempfile.TemporaryDirectory() as temporary,
            AuxiliaryTextRuntime(
                Path(PYTHON), Path(MODELS), Path(temporary), cancel=cancel
            ) as reader,
        ):
            row = original_row("BRD9")
            reader.observe(row, timeout=60)
            process = reader.worker_process
            cancel.set()
            with self.assertRaises(TextOCRCancelled):
                reader.observe(row)
            self.assertIsNotNone(process.poll())
