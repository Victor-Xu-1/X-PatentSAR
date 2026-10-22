"""Generated receipt-checked reports; passive draw reads, not private analyses."""

import gc
import hashlib
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import test_sar_study_analysis as support

from patent_sar_extractor.web.errors import WebError
from patent_sar_extractor.web.files import SafeFiles
from patent_sar_extractor.web.sar.models import Molecule, SARJob
from patent_sar_extractor.web.sar.report_preparation import ReportPreparation
from patent_sar_extractor.web.sar.study_models import StudyReport
from patent_sar_extractor.web.sar.study_results import StudyResults
from patent_sar_extractor.web.storage import encode


class StudyDrawingBatchTests(unittest.TestCase):
    setUp = support.StudyAnalysisTests.setUp
    packet = support.StudyAnalysisTests.packet
    write = support.StudyAnalysisTests.write
    run_packet = support.StudyAnalysisTests.run_packet

    def source(self):
        packet = self.packet(regions=1)
        _, report = self.run_packet(packet)
        # Actual supported large-input boundary. Whitespace changes no chemistry.
        content = b" " * (4 * 1024 * 1024) + encode(report.model_dump()).encode()
        (self.root / "report.json").write_bytes(content)
        digest = hashlib.sha256(content).hexdigest()
        job = SARJob(
            id=self.root.name,
            dataset_id=report.dataset_id,
            region_id=report.regions[0].region.id,
            kind="study",
            status="complete",
            metric_id="activity",
            total=report.molecule_count,
            input_sha256=report.input_sha256,
            created_at="2026-01-01T00:00:00Z",
        )
        molecules = {
            row["id"]: Molecule.model_validate(row) for row in packet["molecules"]
        }

        def molecule(dataset, identifier):
            if identifier not in molecules:
                raise WebError(
                    404, "sar_molecule_missing", "Molecule is not part of this dataset."
                )
            return molecules[identifier]

        queue = SimpleNamespace(
            view=lambda identifier: job,
            jobs=SimpleNamespace(
                record=lambda identifier: {
                    "root": str(self.root),
                    "spec": json.dumps({"report_sha256": digest}),
                }
            ),
            service=SimpleNamespace(
                assets=SimpleNamespace(
                    job_files=lambda root, identifier: SafeFiles(self.root)
                ),
                datasets=SimpleNamespace(molecule=molecule),
            ),
        )
        return StudyResults(queue), list(molecules), content, digest

    def test_sequential_single_draws_reparse_the_same_large_report(self):
        reader, keys, _content, _digest = self.source()
        with (
            patch(
                "patent_sar_extractor.web.sar.study_results.report_preparation",
                ReportPreparation(),
            ),
            patch.object(
                StudyReport,
                "model_validate_json",
                wraps=StudyReport.model_validate_json,
            ) as parser,
        ):
            for key in keys:
                self.assertIn(
                    "</svg>", reader.drawing(self.root.name, "molecule", key).svg
                )
                gc.collect()
        self.assertEqual(parser.call_count, len(keys))

    def test_one_bounded_batch_validates_the_large_report_once(self):
        reader, keys, _content, _digest = self.source()
        with (
            patch(
                "patent_sar_extractor.web.sar.study_results.report_preparation",
                ReportPreparation(),
            ),
            patch.object(
                StudyReport,
                "model_validate_json",
                wraps=StudyReport.model_validate_json,
            ) as parser,
        ):
            result = reader.drawings(self.root.name, "molecule", keys)
        self.assertEqual(parser.call_count, 1)
        self.assertEqual(result.job.id, self.root.name)
        self.assertEqual([item.identifier for item in result.items], keys)
        self.assertTrue(
            all(item.result and "</svg>" in item.result.svg for item in result.items)
        )

    def test_invalid_or_unbounded_batch_never_reads_a_report(self):
        reader = StudyResults(SimpleNamespace())
        with patch.object(
            reader, "load", side_effect=AssertionError("No read for invalid selectors")
        ):
            for kind, keys, region in (
                ("molecule", [], ""),
                ("molecule", ["x"] * 33, ""),
                ("molecule", ["x", "x"], ""),
                ("molecule", [""], ""),
                ("molecule", ["x" * 201], ""),
                ("molecule", [True], ""),
                ("molecule", ["x"], "x" * 201),
                ("unknown", ["x"], ""),
                ([], ["x"], ""),
            ):
                with self.subTest(kind=kind, keys=keys):
                    with self.assertRaises(WebError) as error:
                        reader.drawings("controlled", kind, keys, region)
                    self.assertEqual(error.exception.status, 422)

    def test_one_missing_drawing_keeps_other_real_vectors_without_a_placeholder(self):
        reader, keys, _content, _digest = self.source()
        result = reader.drawings(
            self.root.name, "molecule", [keys[0], "absent", keys[1]]
        )
        self.assertEqual(
            [item.identifier for item in result.items], [keys[0], "absent", keys[1]]
        )
        self.assertIsNone(result.items[1].result)
        self.assertEqual(result.items[1].error.code, "sar_molecule_missing")
        self.assertTrue(
            all(
                item.result and "<svg" in item.result.svg
                for item in (result.items[0], result.items[2])
            )
        )

    def test_changed_receipt_is_fatal_before_any_batch_drawing(self):
        reader, keys, content, _digest = self.source()
        (self.root / "report.json").write_bytes(content + b" ")
        with self.assertRaises(WebError) as error:
            reader.drawings(self.root.name, "molecule", keys)
        self.assertEqual(error.exception.code, "sar_report_changed")

    def test_batch_vectors_equal_the_existing_single_reader(self):
        reader, keys, _content, _digest = self.source()
        expected = [reader.drawing(self.root.name, "molecule", key) for key in keys]
        observed = reader.drawings(self.root.name, "molecule", keys)
        self.assertEqual([item.result for item in observed.items], expected)

    def test_scaffold_fragment_and_highlight_use_the_same_renderer(self):
        reader, _keys, _content, _digest = self.source()
        _job, report = reader.load(self.root.name)
        region = report.regions[0]
        cases = [
            ("scaffold", report.scaffolds[0].id, ""),
            ("fragment", region.fragments[0].id, region.region.id),
            ("molecule", region.region.molecule_id, region.region.id),
        ]
        for kind, key, region_id in cases:
            with self.subTest(kind=kind):
                legacy = reader.drawing(self.root.name, kind, key, region_id)
                observed = reader.drawings(self.root.name, kind, [key], region_id)
                self.assertEqual(observed.items[0].result, legacy)
                self.assertIn("<svg", legacy.svg)

    def test_batch_does_not_keep_a_large_model_after_its_last_reader(self):
        reader, keys, _content, _digest = self.source()
        preparation = ReportPreparation()
        with patch(
            "patent_sar_extractor.web.sar.study_results.report_preparation", preparation
        ):
            result = reader.drawings(self.root.name, "molecule", keys)
        self.assertTrue(result.items)
        gc.collect()
        self.assertTrue(preparation._large)
        self.assertTrue(
            all(reference() is None for reference in preparation._large.values())
        )

    def test_response_byte_budget_is_explicit_not_silent_truncation(self):
        reader, keys, _content, _digest = self.source()
        with (
            patch(
                "patent_sar_extractor.web.sar.study_drawings.MAX_DRAWING_BATCH_BYTES",
                128,
            ),
            self.assertRaises(WebError) as error,
        ):
            reader.drawings(self.root.name, "molecule", keys)
        self.assertEqual(error.exception.status, 413)
        self.assertEqual(error.exception.code, "sar_drawing_batch_large")
