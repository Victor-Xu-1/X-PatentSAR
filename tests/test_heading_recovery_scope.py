"""Heading typography has one caller-owned scope through capture and recovery."""

import copy
import hashlib
import json
import unittest
from unittest.mock import patch

import fitz

from patent_sar_extractor.core.binding_source_headings import (
    observed_heading_blocks,
    select_heading_bindings,
)
from patent_sar_extractor.core.cell_text_proof import valid_text_reading
from patent_sar_extractor.core.heading_observation import observe_heading
from patent_sar_extractor.core.heading_original_replay import validate_original_heading
from patent_sar_extractor.core.heading_source_geometry import (
    MAX_HEADING_HEIGHT,
    MAX_HEADING_ROWS,
)
from patent_sar_extractor.core.heading_source_proof import proved_heading_declaration
from patent_sar_extractor.core.source_section_roles import heading_members
from tests import test_auxiliary_cell_evidence as auxiliary


class HeadingRecoveryScopeTests(unittest.TestCase):
    def setUp(self):
        self.native_factory = self.enterContext(
            patch(
                "patent_sar_extractor.core.page_ocr_cache._build_ocr_engine",
                side_effect=AssertionError("No native OCR in generated scope checks"),
            )
        )

    def tearDown(self):
        self.assertEqual(self.native_factory.call_count, 0)

    def source(self, *, fontsize=22, wrapped=False, shadow=False):
        with fitz.open() as original:
            page = original.new_page(width=500, height=330)
            page.insert_text(
                (35, 75),
                "Compounds 27B and" if wrapped else "Compound 27B",
                fontsize=fontsize,
            )
            if wrapped:
                page.insert_text((35, 75 + fontsize * 1.4), "73", fontsize=fontsize)
            words = page.get_text("words")
            box = [
                min(word[0] for word in words),
                min(word[1] for word in words),
                max(word[2] for word in words),
                max(word[3] for word in words),
            ]
            pixels = page.get_pixmap(matrix=fitz.Matrix(3, 3), alpha=False).tobytes(
                "png"
            )
        document = self.enterContext(fitz.open())
        page = document.new_page(width=500, height=330)
        page.insert_image(page.rect, stream=pixels)
        page.insert_text((35, 310), "Generated source footer", fontsize=8)
        if shadow:
            page.insert_text((35, 75), "Compound 74", fontsize=fontsize, render_mode=3)
        nomination = {
            "text": "Compound 999",  # A location nomination never supplies the ID.
            "bbox": box,
            "source": "page_ocr",
            "geometry_space": "rendered",
        }
        digest = hashlib.sha256(document.tobytes(no_new_id=True)).hexdigest()
        return page, nomination, digest

    def observe(self, *, reader=None, wrapped=False, fontsize=22, shadow=False):
        page, nomination, digest = self.source(
            fontsize=fontsize, wrapped=wrapped, shadow=shadow
        )
        texts = ("Compounds 27B and", "73") if wrapped else ("Compound 27B",)
        reader = reader or auxiliary.ControlledAuxiliary(texts)
        with (
            patch(
                "patent_sar_extractor.core.heading_observation.get_ocr_engine",
                return_value=("rapidocr", auxiliary.primary),
            ),
            patch(
                "patent_sar_extractor.core.text_ocr.source_capture.get_auxiliary_text_runtime",
                return_value=reader,
            ),
        ):
            proof = observe_heading(page, nomination, digest, grids=[])
        return page, proof, reader

    def test_large_single_and_wrapped_headings_recover_with_the_same_source_scope(self):
        expected_scope = {
            "maximum_rows": MAX_HEADING_ROWS,
            "maximum_row_height": MAX_HEADING_HEIGHT,
        }
        for fontsize, wrapped in ((16, False), (22, False), (22, True)):
            with self.subTest(fontsize=fontsize, wrapped=wrapped):
                page, proof, reader = self.observe(fontsize=fontsize, wrapped=wrapped)
                saved = json.loads(json.dumps(proof))
                declaration = proved_heading_declaration(saved)
                self.assertIsNotNone(
                    declaration,
                    [
                        (
                            reading["raw_text"],
                            [
                                (
                                    attempt["code"],
                                    [
                                        view["frame"]["shape"]
                                        for view in attempt.get("views", [])
                                    ],
                                )
                                for attempt in reading.get(
                                    "auxiliary_text_attempts", []
                                )
                            ],
                        )
                        for reading in saved["observations"]
                    ],
                )
                self.assertEqual(
                    heading_members(declaration), ["27B", "73"] if wrapped else ["27B"]
                )
                self.assertEqual(saved["nomination"]["text"], "Compound 999")
                self.assertEqual(reader.calls, 4 if wrapped else 2)
                for reading in saved["observations"]:
                    self.assertEqual(reading["text_scope"], expected_scope)
                    packet = reading["auxiliary_text"]
                    self.assertEqual(packet["maximum_row_height"], MAX_HEADING_HEIGHT)
                    self.assertEqual(packet["rows_per_chunk"], MAX_HEADING_ROWS)
                    for view in packet["views"]:
                        self.assertEqual(view["primary"]["text_scope"], expected_scope)
                        self.assertEqual(view["selected"]["text_scope"], expected_scope)
                validate_original_heading(page, saved)

    def test_heading_recovery_does_not_enlarge_an_assay_cell_callers_authority(self):
        _page, proof, _reader = self.observe()
        reading = proof["observations"][0]
        self.assertTrue(
            valid_text_reading(
                reading, proof["bbox"], 400, maximum_row_height=MAX_HEADING_HEIGHT
            )
        )
        self.assertFalse(valid_text_reading(reading, proof["bbox"], 400))
        stripped = copy.deepcopy(reading)
        del stripped["text_scope"]
        self.assertFalse(valid_text_reading(stripped, proof["bbox"], 400))

    def test_original_pixels_and_both_view_limits_remain_mandatory(self):
        page, proof, _reader = self.observe()
        for mutation in ("primary", "selected", "packet"):
            changed = copy.deepcopy(proof)
            packet = changed["observations"][0]["auxiliary_text"]
            if mutation == "packet":
                packet["maximum_row_height"] = 12
            else:
                del packet["views"][0][mutation]["text_scope"]
            with self.subTest(mutation=mutation):
                self.assertIsNone(proved_heading_declaration(changed))
        page.draw_line((37, 70), (43, 70), width=2)
        with self.assertRaises(ValueError):
            validate_original_heading(page, proof)

    def test_two_auxiliary_views_cannot_outvote_a_native_identifier(self):
        _page, proof, _reader = self.observe(shadow=True)
        self.assertIsNone(proved_heading_declaration(proof))
        self.assertIn("74", proof["native_source"]["text"])

    def test_disagreeing_auxiliary_identifiers_are_retained_not_voted(self):
        reader = auxiliary.ControlledAuxiliary(("Compound 27B", "Compound 28B"))
        _page, proof, _reader = self.observe(reader=reader)
        self.assertIsNone(proved_heading_declaration(proof))
        self.assertEqual(reader.calls, 2)
        for reading in proof["observations"]:
            self.assertIn("auxiliary_text_attempts", reading)
            self.assertNotIn("auxiliary_text", reading)

    def test_unchanged_model_row_budget_refuses_oversize_without_resizing(self):
        _page, proof, reader = self.observe(fontsize=30)
        self.assertIsNone(proved_heading_declaration(proof))
        self.assertEqual(
            reader.calls, 1
        )  # The600dpi row exceeds256px before inference.
        for reading in proof["observations"]:
            attempts = reading["auxiliary_text_attempts"]
            self.assertEqual(attempts[-1]["code"], "runtime_or_source_failure")
            self.assertNotIn("auxiliary_text", reading)

    def test_qualified_primary_does_not_load_auxiliary_or_add_resolution_passes(self):
        page, nomination, digest = self.source()
        calls = []

        def good(image, *, use_det, use_cls):
            calls.append((use_det, use_cls))
            return ([], None) if use_det else ([["Compound 27B", 0.99]], None)

        with (
            patch(
                "patent_sar_extractor.core.heading_observation.get_ocr_engine",
                return_value=("rapidocr", good),
            ),
            patch(
                "patent_sar_extractor.core.text_ocr.source_capture.get_auxiliary_text_runtime",
                side_effect=AssertionError("Qualified primary does not load auxiliary"),
            ),
        ):
            proof = observe_heading(page, nomination, digest, grids=[])
        self.assertEqual(heading_members(proved_heading_declaration(proof)), ["27B"])
        self.assertEqual(calls, [(False, False), (False, False)])
        self.assertFalse(any("auxiliary_text" in r for r in proof["observations"]))

    def test_normal_binder_keeps_the_heading_but_does_not_invent_a_product(self):
        page, nomination, _digest = self.source()
        nomination.update(y0=nomination["bbox"][1], y1=nomination["bbox"][3])
        sections = []
        with (
            patch(
                "patent_sar_extractor.core.binding_source_headings.original_heading_lines",
                return_value=[nomination],
            ),
            patch(
                "patent_sar_extractor.core.heading_observation.get_ocr_engine",
                return_value=("rapidocr", auxiliary.primary),
            ),
            patch(
                "patent_sar_extractor.core.text_ocr.source_capture.get_auxiliary_text_runtime",
                return_value=auxiliary.ControlledAuxiliary(("Compound 27B",)),
            ),
        ):
            blocks = observed_heading_blocks(
                page.parent,
                [0],
                {},
                source_sections=sections,
                grids_for_page=lambda _page: [],
            )
        self.assertEqual([block["cpd"] for block in blocks], ["Compound 27B"])
        section = next(item for item in sections if item["role"] == "compound_heading")
        validate_original_heading(page, section["heading_observation"])
        # A title without a proved drawing is not a terminal product or model input.
        bindings, issues = select_heading_bindings(page.parent, [], blocks, {}, "", {})
        self.assertEqual(bindings, [])
        self.assertEqual(
            [issue["reason"] for issue in issues], ["no_heading_structure"]
        )

    def test_oversized_heading_stops_before_primary_or_auxiliary_loading(self):
        page, nomination, digest = self.source()
        nomination["bbox"] = [30, 30, 250, 170]
        with (
            patch(
                "patent_sar_extractor.core.heading_observation.get_ocr_engine",
                side_effect=AssertionError("Source limit precedes model access"),
            ),
            self.assertRaises(ValueError),
        ):
            observe_heading(page, nomination, digest, grids=[])


if __name__ == "__main__":
    unittest.main()
