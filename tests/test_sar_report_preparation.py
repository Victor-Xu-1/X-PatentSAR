"""Real report validation, bounded in-flight reuse and immutable receipt gates."""

import gc
import hashlib
import threading
import unittest
import weakref
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import test_sar_study_analysis as support

from patent_sar_extractor.web.errors import WebError
from patent_sar_extractor.web.sar.report_preparation import ReportPreparation
from patent_sar_extractor.web.sar.study_models import StudyReport
from patent_sar_extractor.web.storage import encode


class ReportPreparationTests(unittest.TestCase):
    setUp = support.StudyAnalysisTests.setUp
    packet = support.StudyAnalysisTests.packet
    write = support.StudyAnalysisTests.write
    run_packet = support.StudyAnalysisTests.run_packet

    def content(self):
        _, report = self.run_packet(self.packet(regions=1))
        # Valid JSON whitespace exercises the actual large-packet boundary;
        # no threshold, schema or private patent fixture is patched.
        content = b" " * (4 * 1024 * 1024) + encode(report.model_dump()).encode()
        return content, hashlib.sha256(content).hexdigest(), report

    def test_concurrent_large_reads_share_one_full_native_validation(self):
        content, digest, expected = self.content()
        cache, started, release = (
            ReportPreparation(),
            threading.Event(),
            threading.Event(),
        )
        original = StudyReport.model_validate_json

        def validate(data):
            started.set()
            if not release.wait(3):
                raise AssertionError("validation_release_missing")
            return original(data)

        with (
            patch.object(
                StudyReport, "model_validate_json", side_effect=validate
            ) as parser,
            ThreadPoolExecutor(max_workers=6) as executor,
        ):
            futures = [executor.submit(cache.read, content, digest) for _ in range(6)]
            self.assertTrue(started.wait(2))
            release.set()
            reports = [future.result(timeout=4) for future in futures]
        self.assertEqual(parser.call_count, 1)
        self.assertTrue(all(report is reports[0] for report in reports))
        self.assertEqual(reports[0].model_dump(), expected.model_dump())

    def test_large_packet_and_model_are_not_retained_after_last_reader(self):
        content, digest, _ = self.content()
        cache = ReportPreparation()
        model = cache.read(content, digest)
        observed = weakref.ref(model)
        del model
        gc.collect()
        self.assertIsNone(observed())
        with patch.object(
            StudyReport, "model_validate_json", wraps=StudyReport.model_validate_json
        ) as parser:
            model = cache.read(content, digest)
        self.assertEqual(parser.call_count, 1)
        self.assertIsInstance(model, StudyReport)

    def test_live_cached_model_cannot_bypass_a_changed_receipt(self):
        content, digest, expected = self.content()
        cache = ReportPreparation()
        model = cache.read(content, digest)
        with patch.object(
            StudyReport,
            "model_validate_json",
            side_effect=AssertionError("cache_bypass"),
        ):
            for data, receipt in ((content + b" ", digest), (content, "0" * 64)):
                with self.assertRaises(WebError) as failure:
                    cache.read(data, receipt)
                self.assertEqual(failure.exception.code, "sar_report_changed")
        self.assertEqual(model.model_dump(), expected.model_dump())

    def test_failed_full_validation_never_creates_a_reusable_model(self):
        content, _, _ = self.content()
        invalid = b" " * (4 * 1024 * 1024) + b'{"schema_version": 1}'
        digest = hashlib.sha256(invalid).hexdigest()
        cache = ReportPreparation()
        with patch.object(
            StudyReport, "model_validate_json", wraps=StudyReport.model_validate_json
        ) as parser:
            for _ in range(2):
                with self.assertRaises(ValueError):
                    cache.read(invalid, digest)
        self.assertEqual(parser.call_count, 2)
        self.assertEqual(len(cache._large), 0)
        valid = cache.read(content, hashlib.sha256(content).hexdigest())
        self.assertIsInstance(valid, StudyReport)

    def test_weak_metadata_is_bounded_even_while_many_distinct_readers_hold_reports(
        self,
    ):
        content, _, _ = self.content()
        cache, held = ReportPreparation(), []
        for index in range(40):
            packet = content + b" " * index
            held.append(cache.read(packet, hashlib.sha256(packet).hexdigest()))
        self.assertEqual(len(held), 40)
        self.assertLessEqual(len(cache._large), 32)
        self.assertTrue(
            all(
                isinstance(reference, weakref.ReferenceType)
                for reference in cache._large.values()
            )
        )


if __name__ == "__main__":
    unittest.main()
