"""Actual generated auxiliary envelopes survive transport, not scientific QA."""

import copy
import json
import tempfile
import unittest
from pathlib import Path

import fitz

from patent_sar_extractor.core.cell_raster import render_cell_raster
from patent_sar_extractor.core.table_cells import observe_original_cell
from patent_sar_extractor.core.text_ocr.cell_capture import refine_text_pair
from patent_sar_extractor.core.text_ocr.cell_proof import replay_auxiliary_cell
from patent_sar_extractor.web.activity_focus import matching_cells
from patent_sar_extractor.web.activity_provenance import cell_evidence, source_evidence
from patent_sar_extractor.web.artifacts import _activities
from patent_sar_extractor.web.errors import WebError
from patent_sar_extractor.web.sar.observation_contexts import ObservationContexts
from tests.test_activity_source_scopes import source_row
from tests.test_auxiliary_cell_evidence import ControlledAuxiliary, primary


class ActivityObservationTransportTests(unittest.TestCase):
    def setUp(self):
        self.document = fitz.open()
        self.addCleanup(self.document.close)
        page = self.document.new_page(width=200, height=160)
        page.insert_text((25, 45), "7.2", fontsize=9)
        bounds = [15, 25, 140, 65]
        images = tuple(
            render_cell_raster(page, bounds, dpi, purpose="text").image
            for dpi in (400, 600)
        )
        primaries = tuple(
            {
                **observe_original_cell(
                    page, bounds, "text", dpi, primary, lambda text, _kind: text
                ).evidence(dpi, bounds),
                "detector_conflict": False,
            }
            for dpi in (400, 600)
        )
        pair = refine_text_pair(images, primaries, ControlledAuxiliary(("7.2",)))
        self.assertIsNotNone(pair)
        for reading in pair:
            self.assertGreater(len(reading), 16)
            self.assertTrue(replay_auxiliary_cell(reading, page))
        self.row = source_row(value="7.2")
        self.cell = self.row["activity_sources"][0]["cells"][1]
        self.cell.update(bbox=bounds, observations=list(pair))

    def test_generated_current_envelope_is_not_a_transport_error(self):
        before = copy.deepcopy(self.row)
        result = source_evidence(self.row, (1, None, None), page_count=1)
        self.assertEqual(result[0].cells[1].value, "7.2")
        self.assertEqual(self.row, before)

    def test_result_projection_and_exact_original_focus_share_the_same_parser(self):
        activities = _activities(self.row, page_count=1)
        sources = source_evidence(self.row, (1, None, None), page_count=1)
        self.assertEqual(len(activities), 1)
        self.assertEqual(activities[0].value, "7.2")
        self.assertEqual(
            matching_cells(sources[0], "1", activities[0]),
            [((15.0, 25.0, 140.0, 65.0), "rendered")],
        )

    def test_sar_context_reader_retains_conditions_without_reinterpreting_evidence(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "activity").mkdir()
            (root / "activity/activity_data.json").write_text(
                json.dumps({"rows": [self.row]}), encoding="utf-8"
            )
            context = ObservationContexts(
                {
                    "run_root": directory,
                    "sha256": "a" * 64,
                    "expected_sha256": "a" * 64,
                    "page_count": 1,
                }
            )
        self.assertTrue(context.exact)
        self.assertIn("HEK293", str(context.exact))
        self.assertIn("24 h", str(context.exact))

    def test_transport_still_rejects_malformed_or_unbounded_observations(self):
        for change in (
            {"observations": [None]},
            {"observations": [{}] * 21},
            {"observations": [{str(i): None for i in range(33)}]},
            {"observations": [{"confidence": True}]},
            {"observations": [{"confidence": float("nan")}]},
            {"observations": [{"text": "x" * 10001}]},
            {"bbox": [15, 65, 140, 25]},
        ):
            with self.subTest(change=change), self.assertRaises(WebError):
                cell_evidence({**self.cell, **change})

    def test_finite_field_budget_is_inclusive_and_does_not_strip_source_data(self):
        observation = copy.deepcopy(self.cell["observations"][0])
        while len(observation) < 32:
            observation[f"reserved_{len(observation)}"] = None
        cell = {**self.cell, "observations": [observation]}
        before = copy.deepcopy(cell)
        self.assertEqual(cell_evidence(cell).value, "7.2")
        self.assertEqual(cell, before)
        observation["one_over_budget"] = None
        with self.assertRaises(WebError):
            cell_evidence(cell)

    def test_transport_success_does_not_qualify_changed_original_pixels(self):
        # Transport reads a bounded envelope; core proof still checks its source.
        self.document[0].insert_text((28, 55), "X", fontsize=8)
        source_evidence(self.row, (1, None, None), page_count=1)
        for observation in self.cell["observations"]:
            self.assertFalse(replay_auxiliary_cell(observation, self.document[0]))
