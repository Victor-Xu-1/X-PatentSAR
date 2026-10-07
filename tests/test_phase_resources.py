"""Owned sequential handoff releases aliases, not other tasks or input caches."""

from __future__ import annotations

import gc
import sys
import tempfile
import threading
import unittest
import weakref
from argparse import Namespace
from contextlib import ExitStack
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch

from patent_sar_extractor.contracts import CORE_STAGE_ORDER
from patent_sar_extractor.core import phase_resources

PAGE = "patent_sar_extractor.core.page_ocr_cache"
PROFILER = "patent_sar_extractor.core.patent_profiler"


class Runtime:
    pass


class PhaseResourceTests(unittest.TestCase):
    def test_pipeline_releases_only_after_completed_or_failed_binding_handler(self):
        from patent_sar_extractor.application import pipeline

        for failing in (None, "bind", "structures"):
            with (
                self.subTest(failing=failing),
                tempfile.TemporaryDirectory() as output,
                ExitStack() as stack,
            ):
                events = []

                def handler(state, *, name, event_log=events, failure=failing):
                    event_log.append(name)
                    if name == failure:
                        raise RuntimeError("controlled handler failure")

                for stage in CORE_STAGE_ORDER:
                    stack.enter_context(
                        patch.object(
                            pipeline,
                            f"execute_{stage}",
                            side_effect=lambda state, name=stage: handler(
                                state, name=name
                            ),
                        )
                    )
                stack.enter_context(
                    patch.object(pipeline, "_load_io_config", return_value={})
                )
                release = stack.enter_context(
                    patch.object(
                        pipeline,
                        "release_completed_document_phase",
                        side_effect=lambda event_log=events: (
                            event_log.append("release") or {}
                        ),
                    )
                )
                args = Namespace(
                    pdf="controlled.pdf",
                    output=output,
                    patent_id="CONTROL",
                    force=False,
                )
                if failing:
                    with self.assertRaisesRegex(
                        RuntimeError, "controlled handler failure"
                    ):
                        pipeline.execute_pipeline(args, Mock())
                else:
                    pipeline.execute_pipeline(args, Mock())
                if failing == "structures":
                    release.assert_not_called()
                    self.assertEqual(events, list(CORE_STAGE_ORDER[:3]))
                else:
                    release.assert_called_once_with()
                    expected = list(CORE_STAGE_ORDER[:4]) + ["release"]
                    if not failing:
                        expected += list(CORE_STAGE_ORDER[4:])
                    self.assertEqual(events, expected)

    def test_shared_aliases_and_current_thread_release_one_runtime(self):
        page, profiler = ModuleType(PAGE), ModuleType(PROFILER)
        engine = Runtime()
        reference = weakref.ref(engine)
        page._OCR_ENGINE = profiler._OCR_ENGINE = engine
        local = threading.local()
        local.engine, local.initialized = engine, True
        page._THREAD_OCR = local
        page._PDF_HASH_CACHE = {"original.pdf": (1, 2, "source")}
        del engine
        pdf = ModuleType("fitz")
        pdf.TOOLS = SimpleNamespace(store_shrink=Mock())
        with (
            patch.dict(sys.modules, {PAGE: page, PROFILER: profiler, "fitz": pdf}),
            patch.object(phase_resources, "_rss_mb", side_effect=[800.0, 300.0]),
            patch.object(phase_resources, "_trim_allocator", return_value=True),
        ):
            result = phase_resources.release_completed_document_phase()
        self.assertIsNone(reference())
        self.assertIsNone(page._OCR_ENGINE)
        self.assertIsNone(profiler._OCR_ENGINE)
        self.assertIsNone(local.engine)
        self.assertFalse(local.initialized)
        self.assertEqual(page._PDF_HASH_CACHE, {"original.pdf": (1, 2, "source")})
        self.assertEqual(result["released_ocr_runtimes"], 1)
        self.assertEqual(
            (result["rss_before_mb"], result["rss_after_mb"]), (800.0, 300.0)
        )
        pdf.TOOLS.store_shrink.assert_called_once_with(100)

    def test_distinct_owned_runtimes_release_without_loading_any_new_engine(self):
        page, profiler = ModuleType(PAGE), ModuleType(PROFILER)
        page._OCR_ENGINE, profiler._OCR_ENGINE = Runtime(), Runtime()
        page._build_ocr_engine = Mock(side_effect=AssertionError("must not initialize"))
        with patch.dict(sys.modules, {PAGE: page, PROFILER: profiler}):
            result = phase_resources.release_completed_document_phase()
        self.assertEqual(result["released_ocr_runtimes"], 2)
        page._build_ocr_engine.assert_not_called()

    def test_unavailable_runtime_is_not_reinitialized(self):
        page, profiler = ModuleType(PAGE), ModuleType(PROFILER)
        page._OCR_ENGINE, profiler._OCR_ENGINE = False, None
        with patch.dict(sys.modules, {PAGE: page, PROFILER: profiler}):
            first = phase_resources.release_completed_document_phase()
            second = phase_resources.release_completed_document_phase()
        self.assertEqual(first["released_ocr_runtimes"], 0)
        self.assertEqual(second["released_ocr_runtimes"], 0)
        self.assertIs(page._OCR_ENGINE, False)

    def test_pdf_trim_failure_is_explicit_and_keeps_memory_admission_authority(self):
        pdf = ModuleType("fitz")
        pdf.TOOLS = SimpleNamespace(
            store_shrink=Mock(side_effect=RuntimeError("controlled failure"))
        )
        with (
            patch.dict(sys.modules, {"fitz": pdf}),
            self.assertLogs(phase_resources.logger, "WARNING"),
        ):
            result = phase_resources.release_completed_document_phase()
        self.assertFalse(result["pdf_cache_trimmed"])

    def test_unrelated_live_runtime_is_not_released(self):
        other = ModuleType("unrelated_science")
        other._OCR_ENGINE = Runtime()
        identity = id(other._OCR_ENGINE)
        with patch.dict(sys.modules, {"unrelated_science": other}):
            phase_resources.release_completed_document_phase()
        self.assertEqual(id(other._OCR_ENGINE), identity)
        gc.collect()

    def test_unsupported_allocator_is_reported_not_faked(self):
        with patch.object(phase_resources.sys, "platform", "win32"):
            self.assertFalse(phase_resources._trim_allocator())
        with patch.object(
            phase_resources.ctypes, "CDLL", return_value=SimpleNamespace()
        ):
            self.assertFalse(phase_resources._trim_allocator())
