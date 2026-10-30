"""Observed page work shares the owned progress channel, never scientific QA."""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import fitz

from patent_sar_extractor.application.classification_progress import (
    ClassificationProgress,
)
from patent_sar_extractor.application.progress import PipelineProgress
from patent_sar_extractor.application.stage_classify import execute_classify
from patent_sar_extractor.artifact_io import write_json_atomic
from patent_sar_extractor.contracts import (
    RUN_SUMMARY_SCHEMA,
    RUN_SUMMARY_SCHEMA_VERSION,
    STAGE_PROGRESS_SCHEMA,
    STAGE_PROGRESS_SCHEMA_VERSION,
    artifact_identity,
    schema_ref,
)
from patent_sar_extractor.core import page_ocr_cache as caches
from patent_sar_extractor.core.page_classifier import classify_pdf
from patent_sar_extractor.web.files import SafeFiles
from patent_sar_extractor.web.models import STAGES
from patent_sar_extractor.web.stages import (
    read_progress,
    read_summary,
    stages_from_summary,
)


class ClassificationProgressTests(unittest.TestCase):
    def test_page_work_browser_scope_uses_only_existing_read_only_fixture(self):
        from tools.browser_fixture_mode import fixture_mode

        selected = {
            "frontend/e2e/classification-source-progress.spec.ts",
            "frontend/e2e/binding-source-progress.spec.ts",
        }
        self.assertEqual(fixture_mode(selected), "read-only")
        self.assertEqual(
            fixture_mode(selected | {"frontend/e2e/product-version.spec.ts"}),
            "read-only",
        )
        self.assertEqual(
            fixture_mode(selected | {"frontend/e2e/unregistered-execution.spec.ts"}),
            "execution",
        )

    def test_original_page_work_is_readable_from_the_existing_stage_channel(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_json_atomic(
                root / "page_classification/progress.json",
                {
                    "schema": schema_ref(
                        STAGE_PROGRESS_SCHEMA, STAGE_PROGRESS_SCHEMA_VERSION
                    ),
                    "stage": "classify",
                    "phase": None,
                    "source_phase": "page_ocr",
                    "completed": 7,
                    "total": 13,
                    "cache_hits": 2,
                    "failures": 0,
                    "device": None,
                    "peak_rss_mb": None,
                },
            )
            progress = read_progress(SafeFiles(root), "classify")
            self.assertIsNotNone(progress)
            self.assertEqual(
                (progress.completed, progress.total, progress.cache_hits), (7, 13, 2)
            )
            self.assertEqual(progress.source_phase, "page_ocr")

    def test_foreign_phases_and_invalid_counters_do_not_become_page_progress(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            writer = ClassificationProgress(str(root / "page_classification"))
            writer("page_ocr", 2, 9, 1)
            original = json.loads(writer.path.read_text())
            for changes in (
                {"source_phase": "heading_sources"},
                {"stage": "bind"},
                {"completed": True},
                {"total": "9"},
                {"cache_hits": 3},
                {"completed": 10},
                {"phase": "recognition"},
            ):
                with self.subTest(changes=changes):
                    write_json_atomic(writer.path, {**original, **changes})
                    self.assertIsNone(read_progress(SafeFiles(root), "classify"))
            other = root / "structure_bindings/progress.json"
            write_json_atomic(other, {**original, "stage": "bind"})
            self.assertIsNone(read_progress(SafeFiles(root), "bind"))


class PageWorkWriterTests(unittest.TestCase):
    def test_monotonic_phases_throttle_and_final_counts_share_the_existing_schema(self):
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch(
                "patent_sar_extractor.application.classification_progress.time.monotonic",
                return_value=1.0,
            ),
        ):
            writer = ClassificationProgress(temporary)
            writer("page_ocr", 2, 4, 2)
            before = writer.path.read_bytes()
            writer("page_ocr", 3, 4, 2)
            self.assertEqual(
                writer.path.read_bytes(), before
            )  # Same bounded 0.5s throttle.
            writer("page_ocr", 4, 4, 2)
            self.assertEqual(json.loads(writer.path.read_text())["completed"], 4)
            writer("empty_text_retry", 0, 1, 0)
            writer("empty_text_retry", 1, 1, 0)
            writer("page_classification", 0, 4, 0)
            writer("page_classification", 4, 4, 0)
            value = json.loads(writer.path.read_text())
            self.assertEqual(value["source_phase"], "page_classification")
            self.assertEqual(value["stage"], "classify")
            self.assertEqual(value["failures"], 0)

    def test_invalid_regression_or_unfinished_phase_cannot_overwrite_observations(self):
        for event in (
            ("page_ocr", True, 5, 0),
            ("page_ocr", 1, 6, 0),
            ("page_ocr", 0, 5, 0),
            ("page_ocr", 2, 5, 1),
            ("page_ocr", 6, 5, 0),
            ("page_ocr", 2, 1_000_001, 0),
            ("page_classification", 0, 5, 0),
            ("heading_sources", 1, 5, 0),
        ):
            with self.subTest(event=event), tempfile.TemporaryDirectory() as temporary:
                writer = ClassificationProgress(temporary)
                writer("page_ocr", 1, 5, 0)
                before = writer.path.read_bytes()
                with self.assertRaises(ValueError):
                    writer(*event)
                self.assertEqual(writer.path.read_bytes(), before)

    def test_new_writer_discards_transported_work_not_source_or_scientific_data(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "page_classification.json"
            source.write_bytes(b"preserved synthetic classification")
            writer = ClassificationProgress(temporary)
            writer("page_ocr", 3, 3, 0)
            ClassificationProgress(temporary)
            payload = json.loads(writer.path.read_text())
            self.assertIsNone(payload["source_phase"])
            self.assertEqual(payload["completed"], 0)
            self.assertEqual(source.read_bytes(), b"preserved synthetic classification")


class OriginalPageWorkTests(unittest.TestCase):
    def setUp(self):
        temporary = self.enterContext(tempfile.TemporaryDirectory())
        self.root = Path(temporary)
        self.pdf = self.root / "original.pdf"
        with fitz.open() as document:
            for index in range(3):
                page = document.new_page()
                page.insert_text(
                    (40, 80),
                    f"Example {index + 1}. Original native synthetic synthesis IC50 source.",
                )
            document.save(self.pdf)
        self.enterContext(
            patch.object(
                caches,
                "_build_ocr_engine",
                side_effect=AssertionError("Native controls cannot acquire OCR models"),
            )
        )
        self.enterContext(
            patch.object(
                caches,
                "get_ocr_engine",
                side_effect=AssertionError("Native controls cannot acquire OCR models"),
            )
        )

    def test_ordered_native_classifier_bytes_stay_identical_with_work_observer(self):
        output = self.root / "page_classification"
        actual_update = caches.update_page_ocr_cache

        def ordered(*args, **kwargs):
            return actual_update(*args, **{**kwargs, "workers": 1})

        self.enterContext(
            patch(
                "patent_sar_extractor.core.page_classifier.update_page_ocr_cache",
                side_effect=ordered,
            )
        )
        original = classify_pdf(str(self.pdf), str(output), force_ocr_cache=True)
        paths = [
            output / name
            for name in ("page_ocr_cache.json", "page_classification.json")
        ]
        saved = {path: path.read_bytes() for path in paths}
        writer = ClassificationProgress(str(output))
        events = []

        def observe(*event):
            events.append(event)
            writer(*event)

        observed = classify_pdf(
            str(self.pdf), str(output), force_ocr_cache=True, progress=observe
        )
        self.assertEqual(original, observed)
        self.assertEqual({path: path.read_bytes() for path in paths}, saved)
        self.assertEqual(events[0], ("page_ocr", 0, 3, 0))
        self.assertEqual(events[-1], ("page_classification", 3, 3, 0))
        result = read_progress(SafeFiles(self.root), "classify")
        self.assertIsNotNone(result)
        self.assertEqual(
            (result.completed, result.total, result.source_phase),
            (3, 3, "page_classification"),
        )

    def test_parallel_native_source_values_are_unchanged_without_assuming_completion_order(
        self,
    ):
        output = self.root / "parallel"
        before_pdf = self.pdf.read_bytes()
        original = classify_pdf(str(self.pdf), str(output), force_ocr_cache=True)
        source = json.loads((output / "page_ocr_cache.json").read_text())
        events = []
        observed = classify_pdf(
            str(self.pdf),
            str(output),
            force_ocr_cache=True,
            progress=lambda *e: events.append(e),
        )
        # Existing as-completed thread scheduling may change JSON object-key order
        # even without observers; it must not change any original source value.
        self.assertEqual(original, observed)
        self.assertEqual(
            json.loads((output / "page_ocr_cache.json").read_text()), source
        )
        self.assertEqual(self.pdf.read_bytes(), before_pdf)
        self.assertEqual(events[-1], ("page_classification", 3, 3, 0))

    def test_cached_partial_requested_subset_and_force_are_distinct_observed_work(self):
        target = self.root / "cache.json"
        caches.update_page_ocr_cache(str(self.pdf), [0], str(target))
        events = []
        caches.update_page_ocr_cache(
            str(self.pdf), [0, 1, 2], str(target), progress=lambda *e: events.append(e)
        )
        self.assertEqual(events[0], ("page_ocr", 1, 3, 1))
        self.assertEqual(events[-1], ("page_ocr", 3, 3, 1))
        events.clear()
        before = target.read_bytes()
        caches.update_page_ocr_cache(
            str(self.pdf), [0, 2], str(target), progress=lambda *e: events.append(e)
        )
        self.assertEqual(events, [("page_ocr", 2, 2, 2)])
        self.assertEqual(target.read_bytes(), before)
        events.clear()
        caches.update_page_ocr_cache(
            str(self.pdf),
            [0, 1, 2],
            str(target),
            force=True,
            progress=lambda *e: events.append(e),
        )
        self.assertEqual(events[0], ("page_ocr", 0, 3, 0))
        self.assertEqual(events[-1], ("page_ocr", 3, 3, 0))

    def test_empty_retry_has_its_own_actual_subset_not_a_regressed_full_document(self):
        events = []
        with patch.object(
            caches,
            "_page_observations",
            side_effect=[
                iter([(0, "Original zero", []), (1, "", []), (2, "Original two", [])]),
                iter([(1, "Original retry one", [])]),
            ],
        ) as reader:
            result = caches.update_page_ocr_cache(
                str(self.pdf),
                [0, 1, 2],
                str(self.root / "retry.json"),
                progress=lambda *e: events.append(e),
            )
        self.assertEqual(
            events[-3:],
            [
                ("page_ocr", 3, 3, 0),
                ("empty_text_retry", 0, 1, 0),
                ("empty_text_retry", 1, 1, 0),
            ],
        )
        self.assertEqual(reader.call_args.args[1], [1])
        self.assertEqual(result["page_texts"]["1"], "Original retry one")

    def test_failed_page_keeps_completed_work_and_checkpoint_without_false_finish(self):
        def observe(*_args):
            yield 0, "Original observed zero", []
            raise RuntimeError("Controlled unavailable original page")

        events = []
        target = self.root / "failed.json"
        with (
            patch.object(caches, "_page_observations", side_effect=observe),
            self.assertRaises(RuntimeError),
        ):
            caches.update_page_ocr_cache(
                str(self.pdf),
                [0, 1, 2],
                str(target),
                progress=lambda *e: events.append(e),
            )
        self.assertEqual(events[-1], ("page_ocr", 1, 3, 0))
        self.assertEqual(set(json.loads(target.read_text())["page_texts"]), {"0"})

    def test_formal_stage_wires_observer_but_reused_checkpoint_is_not_fresh_work(self):
        progress = PipelineProgress()
        log = {
            **artifact_identity(RUN_SUMMARY_SCHEMA, RUN_SUMMARY_SCHEMA_VERSION),
            "main_chain": list(STAGES),
            "steps": {},
            "runtime": {},
            "status": "running",
        }
        progress.bind(str(self.root), log)
        state = SimpleNamespace(
            args=SimpleNamespace(pdf=str(self.pdf)),
            force=False,
            patent_id="SYNTHETIC",
            step_dirs={"classify": str(self.root / "page_classification")},
            pipeline_log=log,
            progress=progress,
        )
        execute_classify(state)
        observed = read_progress(SafeFiles(self.root), "classify")
        self.assertIsNotNone(observed)
        self.assertEqual(observed.completed, 3)
        summary = read_summary(self.root)
        self.assertIsNotNone(summary)
        projected = stages_from_summary(summary, SafeFiles(self.root))
        current = next(stage for stage in projected if stage.name == "classify")
        self.assertEqual(
            current.status, "running"
        )  # The coordinator has not sealed the step.
        self.assertIsNone(current.count)
        self.assertEqual(current.progress.source_phase, "page_classification")
        self.assertEqual(current.progress.completed, 3)
        self.assertTrue(
            all(
                stage.status == "pending"
                for stage in projected
                if stage.name != "classify"
            )
        )
        self.assertEqual(log["steps"]["classify"]["status"], "ok")
        scientific = copy.deepcopy(state.classification)
        execute_classify(state)
        self.assertEqual(state.classification, scientific)
        self.assertTrue(log["steps"]["classify"]["from_cache"])
        self.assertIsNone(read_progress(SafeFiles(self.root), "classify"))
