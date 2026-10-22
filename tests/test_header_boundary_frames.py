"""Original closed cells, not padded page locators, own scanned header bounds.

Recognition is a controlled row adapter. These are original geometry/proof
regressions, not native model accuracy evaluation or private PDF processing.
"""

import copy
import json
import unittest
from contextlib import nullcontext
from itertools import cycle
from unittest.mock import patch

import fitz

from patent_sar_extractor.core.activity_auxiliary_replay import (
    original_activity_source_errors,
)
from patent_sar_extractor.core.activity_header_columns import (
    HeaderColumns,
    observe_header_columns,
)
from patent_sar_extractor.core.activity_header_evidence import (
    proof_id,
    validate_header_evidence,
)
from patent_sar_extractor.core.activity_header_observation import refine_scanned_header
from patent_sar_extractor.core.activity_header_pair import observe_header_pair
from patent_sar_extractor.core.activity_header_proof import valid_header_proof
from patent_sar_extractor.core.activity_headers import context_from_text, grid_schema
from patent_sar_extractor.core.cell_frame_proof import original_cell_frame_matches
from tests.test_auxiliary_cell_evidence import ControlledAuxiliary
from tests.test_source_hint_authority import source_tokens, token


class HeaderBoundaryFrameTests(unittest.TestCase):
    def original(self, header="IC50 (nM)", *, frame=True, attached=False):
        document = self.enterContext(fitz.open())
        page = document.new_page(width=300, height=200)
        self.region = {"xs": [20, 90, 250], "ys": [70, 112, 145]}
        page.insert_text((22, 50), "Table 9. Binding assay", fontsize=9)
        page.insert_text((42, 90), "No.", fontsize=9)
        page.insert_text((112, 90), header, fontsize=9)
        if frame:
            for left, right in zip(self.region["xs"], self.region["xs"][1:]):
                page.draw_rect(fitz.Rect(left, 70, right, 112), width=0.4)
                page.draw_rect(fitz.Rect(left, 112, right, 145), width=0.4)
        if attached:
            page.draw_line((90, 88), (116, 88), width=0.4)
        return self.scan(page)

    def scan(self, page):
        # This is a raster observation: every consumer receives its actual scan,
        # not an empty native-witness declaration over a native-text document.
        scan = self.enterContext(fitz.open())
        original = scan.new_page(width=300, height=200)
        original.insert_image(
            original.rect,
            stream=page.get_pixmap(matrix=fitz.Matrix(4, 4)).tobytes("png"),
        )
        return original

    def locators(self, text="Unknown", confidence=0.2, *, native=False):
        observed = token(text, confidence, 135, 86)
        observed["bbox"] = [84, 76, 186, 96]
        if native:
            observed.update(source="native", confidence=1.0)
        return source_tokens(
            [
                {
                    **token("Table 9. Binding assay", 0.99, 90, 46),
                    "bbox": [20, 38, 170, 54],
                },
                token("No.", 0.99, 55, 86),
                observed,
            ]
        )

    def observe(self, page, tokens, header="IC50 (nM)", score=0.999):
        replies = cycle((("No.", 0.999), (header, score)))

        def engine(image, *, use_det, use_cls):
            self.assertFalse(use_cls)
            if use_det:
                return [], None  # Unbounded/attached source is never recognized away.
            text, confidence = next(replies)
            return [[text, confidence]], None

        with patch(
            "patent_sar_extractor.core.activity_header_columns.get_ocr_engine",
            return_value=("rapidocr", engine),
        ):
            return observe_header_pair(
                page, self.region, 1, tokens, observe_header_columns
            )

    def test_complete_closed_cell_recovers_weak_crossing_locator_without_model_vote(
        self,
    ):
        for header in ("IC50 (nM)", "EC50 (uM)", "Dmax (%)"):
            with self.subTest(header=header):
                page = self.original(header)
                tokens = self.locators()
                before = copy.deepcopy(list(tokens))
                with patch(
                    "patent_sar_extractor.core.activity_header_pair.get_auxiliary_text_runtime",
                    side_effect=AssertionError(
                        "Qualified full cells need no auxiliary vote"
                    ),
                ):
                    views = self.observe(page, tokens, header)
                self.assertEqual(list(tokens), before)
                for view in views:
                    self.assertTrue(view.verified[1])
                    cell = view.columns[1]
                    self.assertFalse(cell["crosses_boundary"])
                    self.assertIsNotNone(cell["source_window"]["frame_strips"])
                    self.assertEqual(
                        cell["boundary_source"]["tokens"][0]["text"], "Unknown"
                    )
                    self.assertTrue(original_cell_frame_matches(cell, page))

    def test_open_or_attached_original_frame_never_resolves_a_crossing(self):
        for settings in ({"frame": False}, {"attached": True}):
            with self.subTest(settings=settings):
                page = self.original(**settings)
                with patch(
                    "patent_sar_extractor.core.activity_header_pair.get_auxiliary_text_runtime",
                    return_value=None,
                ):
                    views = self.observe(page, self.locators())
                self.assertFalse(views[0].verified[1])
                self.assertTrue(views[0].columns[1]["crosses_boundary"])

    def test_qualified_endpoint_unit_and_native_conflicts_are_not_geometric_noise(self):
        for text, confidence, native in (
            ("EC50 (nM)", 0.99, False),
            ("IC50 (uM)", 0.99, False),
            ("Unknown", 1.0, True),
        ):
            with self.subTest(text=text, native=native):
                page = self.original()
                with patch(
                    "patent_sar_extractor.core.activity_header_pair.get_auxiliary_text_runtime",
                    return_value=None,
                ):
                    views = self.observe(
                        page, self.locators(text, confidence, native=native)
                    )
                self.assertFalse(any(view.verified[1] for view in views))

    def proof(self):
        page = self.original()
        tokens = self.locators()
        views = self.observe(page, tokens)
        with (
            patch(
                "patent_sar_extractor.core.activity_header_observation.observe_header_pair",
                return_value=views,
            ),
            patch(
                "patent_sar_extractor.core.activity_header_observation.ocr_tokens_with_positions",
                return_value=tokens,
            ),
        ):
            original = grid_schema(
                context_from_text("Table 9. Binding assay"), [["No.", "Unknown"]]
            )
            result = refine_scanned_header(page, self.region, original, tokens=tokens)
        proof = json.loads(json.dumps(result.header_resolution))
        proof["page_no"] = 1
        proof["table_bbox"] = [20, 70, 250, 145]
        return page, proof

    def test_complete_saved_proof_and_original_replay_preserve_the_boundary_witness(
        self,
    ):
        page, proof = self.proof()
        self.assertEqual(proof["status"], "observed_header_consensus")
        self.assertTrue(valid_header_proof(proof))
        for view in proof["observations"]:
            self.assertTrue(original_cell_frame_matches(view["columns"][1], page))

    def test_saved_source_inventory_replays_new_boundary_proof_against_actual_scan(
        self,
    ):
        page, proof = self.proof()
        payload = {
            "header_observations": {proof_id(proof): proof},
            "rows": [],
            "coverage": {
                "regions": [
                    {
                        "page_no": 1,
                        "bbox": proof["table_bbox"],
                        "grid_axes": self.region,
                    }
                ]
            },
        }

        def read():
            return nullcontext(page.parent)

        self.assertEqual(validate_header_evidence(payload), [])
        self.assertEqual(
            original_activity_source_errors(payload, open_original=read), []
        )
        self.assertIn(
            "Original PDF is required",
            " ".join(original_activity_source_errors(payload)),
        )
        page.draw_line((150, 74), (150, 108), width=0.5)
        self.assertIn(
            "original page pixels",
            " ".join(original_activity_source_errors(payload, open_original=read)),
        )

    def test_missing_changed_or_old_contract_boundary_witness_cannot_be_rehashed(self):
        _, proof = self.proof()
        self.assertTrue(valid_header_proof(proof))

        def downgrade_without_witnesses(value):
            value["column_contract"] = 4
            for observed in value["observations"]:
                for column in observed["columns"]:
                    column.pop("boundary_source", None)

        for mutate in (
            lambda p: p["observations"][0]["columns"][1].pop("boundary_source"),
            lambda p: p["observations"][0]["columns"][1]["boundary_source"]["tokens"][
                0
            ].update(confidence=0.99),
            lambda p: p["observations"][0]["columns"][1]["source_window"].update(
                frame_strips=None
            ),
            lambda p: p.update(column_contract=4),
            lambda p: p["original_source"].pop("columns"),
            lambda p: p["original_source"].update(columns=[]),
            downgrade_without_witnesses,
        ):
            changed = copy.deepcopy(proof)
            mutate(changed)
            self.assertFalse(valid_header_proof(changed))

    def test_weak_owned_read_can_use_the_existing_bounded_auxiliary_path(self):
        page = self.original()
        tokens = self.locators()
        views = self.observe(page, tokens)
        primaries = []
        for view in views:
            columns = copy.deepcopy(list(view.columns))
            cell = columns[1]
            cell.update(raw_text="Unreadable", text="", confidence=0.2)
            cell["parts"][0].update(text="Unreadable", confidence=0.2)
            primaries.append(
                HeaderColumns([["No.", "Unreadable"]], tuple(columns), (True, False))
            )
        reader = ControlledAuxiliary(("IC50 (nM)", "IC50 (nM)"))
        with patch(
            "patent_sar_extractor.core.activity_header_pair.get_auxiliary_text_runtime",
            return_value=reader,
        ):
            recovered = observe_header_pair(
                page, self.region, 1, tokens, lambda *args: primaries.pop(0)
            )
        self.assertEqual(reader.calls, 2)
        for view in recovered:
            self.assertTrue(view.verified[1])
            cell = view.columns[1]
            self.assertEqual(cell["raw_text"], "IC50 (nM)")
            self.assertEqual(cell["boundary_source"]["tokens"][0]["confidence"], 0.2)
            self.assertIn("auxiliary_text", cell)
            self.assertTrue(original_cell_frame_matches(cell, page))

    def test_invalid_locator_confidence_stays_a_rejection_not_a_weak_hint(self):
        page = self.original()
        with patch(
            "patent_sar_extractor.core.activity_header_pair.get_auxiliary_text_runtime",
            return_value=None,
        ):
            views = self.observe(page, self.locators(confidence=float("nan")))
        self.assertFalse(any(view.verified[1] for view in views))

    def test_two_physical_header_rows_keep_each_closed_cell_witness(self):
        self.region = {"xs": [20, 90, 250], "ys": [70, 98, 124, 145]}
        clean = self.enterContext(fitz.open())
        page = clean.new_page(width=300, height=200)
        page.insert_text((22, 50), "Table 9. Binding assay", fontsize=9)
        page.insert_text((42, 90), "No.", fontsize=9)
        page.insert_text((112, 90), "IC50", fontsize=9)
        page.insert_text((112, 116), "nM", fontsize=9)
        for left, right in zip(self.region["xs"], self.region["xs"][1:]):
            for top, bottom in ((70, 98), (98, 124)):
                page.draw_rect(fitz.Rect(left, top, right, bottom), width=0.4)
        page = self.scan(page)
        parts = list(self.locators()) + [token("nM", 0.99, 124, 112)]
        tokens = source_tokens(parts)
        replies = cycle(("No.", "IC50", "nM"))

        def engine(image, *, use_det, use_cls):
            return ([], None) if use_det else ([[next(replies), 0.999]], None)

        with patch(
            "patent_sar_extractor.core.activity_header_columns.get_ocr_engine",
            return_value=("rapidocr", engine),
        ):
            views = [
                observe_header_columns(page, self.region, 2, dpi, tokens)
                for dpi in (400, 600)
            ]
        result = views[0]
        self.assertTrue(result.verified[1])
        self.assertEqual(result.columns[1]["raw_text"], "IC50\nnM")
        self.assertIn("boundary_source", result.columns[1]["header_cells"][0])
        self.assertNotIn("boundary_source", result.columns[1]["header_cells"][1])
        original = grid_schema(
            context_from_text("Table 9. Binding assay"), result.matrix
        )
        with (
            patch(
                "patent_sar_extractor.core.activity_header_observation.observe_header_pair",
                return_value=views,
            ),
            patch(
                "patent_sar_extractor.core.activity_header_observation.ocr_tokens_with_positions",
                return_value=tokens,
            ),
        ):
            resolved = refine_scanned_header(page, self.region, original, tokens=tokens)
        proof = json.loads(json.dumps(resolved.header_resolution))
        self.assertTrue(valid_header_proof(proof))

    def test_changed_original_pixels_cannot_replay_a_saved_closed_cell(self):
        page, proof = self.proof()
        cell = proof["observations"][0]["columns"][1]
        self.assertTrue(original_cell_frame_matches(cell, page))
        page.draw_line((150, 74), (150, 108), width=0.5)
        self.assertFalse(original_cell_frame_matches(cell, page))
