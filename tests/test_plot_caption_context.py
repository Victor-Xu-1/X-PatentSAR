"""An original figure's complete axis strip ends before its own caption."""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from catalog_source_support import original_catalogue

from patent_sar_extractor import contracts
from patent_sar_extractor.artifact_io import write_json_atomic
from patent_sar_extractor.core import page_ocr_cache
from patent_sar_extractor.core.binding_source_references import reference_issues
from patent_sar_extractor.core.formal_structure import coverage_errors
from patent_sar_extractor.core.heading_evidence import original_heading_lines
from patent_sar_extractor.core.heading_source_proof import proved_heading_declaration
from patent_sar_extractor.core.ocsr.recognition_inputs import recognition_inputs
from patent_sar_extractor.core.plot_original_replay import original_plot_source_errors
from patent_sar_extractor.core.plot_reference_geometry import plot_axis_nomination
from patent_sar_extractor.core.text_ocr import configuration
from patent_sar_extractor.web.compound_catalog import read_compound_catalog
from tests.test_plot_reference_layout import observe, plot_document


class PlotCaptionContextTests(unittest.TestCase):
    def setUp(self):
        self.primary = self.enterContext(
            patch.object(
                page_ocr_cache,
                "_build_ocr_engine",
                side_effect=AssertionError("Generated native source needs no OCR"),
            )
        )
        self.auxiliary = self.enterContext(
            patch.object(
                configuration,
                "get_auxiliary_text_runtime",
                side_effect=AssertionError("No auxiliary inference is authorized"),
            )
        )

    def tearDown(self):
        self.primary.assert_not_called()
        self.auxiliary.assert_not_called()

    @staticmethod
    def outside_prose(page, *, numbered=False):
        for line in range(10):
            page.insert_text(
                (25, 395 + line * 7),
                " ".join(
                    str(1000 + line * 30 + word) if numbered else "note"
                    for word in range(30)
                ),
                fontsize=3.5,
            )

    def observe_with_controlled_axis_reader(
        self, document, *, last_tick="100", action=None
    ):
        # Only the OCR transport is scripted. Actual generated source pixels,
        # complete physical word frames, native contradictions and all saved
        # proof/original replay still use production implementations. This is
        # not a native-model benchmark or an accuracy claim.
        expected = ["0.001", "0.1", "1", last_tick] * 2 + ["90", "45", "0"] * 2
        calls = []

        def read(_image, *, use_det, use_cls):
            self.assertFalse(use_det)
            self.assertFalse(use_cls)
            self.assertLess(len(calls), len(expected))
            calls.append(expected[len(calls)])
            return [[calls[-1], 0.99]], None

        with patch(
            "patent_sar_extractor.core.plot_axis_words.get_ocr_engine",
            return_value=("rapidocr", read),
        ):
            result = observe(document) if action is None else action()
        self.assertEqual(calls, expected)
        return result

    def test_below_caption_body_is_not_part_of_the_axis_nomination_budget(self):
        for numbered in (False, True):
            with self.subTest(numbered=numbered), plot_document() as document:
                page = document[0]
                self.outside_prose(page, numbered=numbered)
                tokens = page.get_text("words")
                original = [{"text": w[4], "bbox": list(w[:4])} for w in tokens]
                lines = original_heading_lines(page)
                caption = next(row for row in lines if row["text"] == "FIGURE 8A")
                heading = next(row for row in lines if row["text"] == "Compound 062-C")
                before = copy.deepcopy(original)
                axes = plot_axis_nomination(
                    original, caption, heading["bbox"], [540, 480]
                )
                self.assertIsNotNone(axes)
                self.assertEqual(original, before)
                self.assertEqual(len(axes["x"]), 4)
                blocks, sections = self.observe_with_controlled_axis_reader(document)
                self.assertEqual(
                    blocks, [], [(s["role"], s.get("line_text")) for s in sections]
                )
                self.assertEqual(sections[0]["role"], "figure_label_reference")
                self.assertIsNotNone(
                    proved_heading_declaration(sections[0]["heading_observation"])
                )

    def test_unread_inside_the_figure_is_not_dropped_with_outside_body(self):
        with plot_document(last_tick="n/a") as document:
            self.outside_prose(document[0])
            blocks, sections = self.observe_with_controlled_axis_reader(
                document, last_tick="n/a"
            )
            self.assertEqual([row["cpd"] for row in blocks], ["Compound 062-C"])
            self.assertFalse(
                any(row["role"] == "figure_label_reference" for row in sections)
            )

    def test_nearby_actual_synthesis_remains_a_separate_original_obligation(self):
        with plot_document(synthesis=True) as document:
            self.outside_prose(document[0])
            blocks, sections = self.observe_with_controlled_axis_reader(document)
            self.assertEqual([row["cpd"] for row in blocks], ["Compound 29"])
            self.assertTrue(
                any(row["role"] == "figure_label_reference" for row in sections)
            )

    def test_the_in_figure_budget_is_not_replaced_by_a_successful_prefix(self):
        with plot_document() as document:
            for line in range(10):
                document[0].insert_text(
                    (20, 140 + line * 7), " ".join(["unknown"] * 30), fontsize=2
                )
            original = [
                {"text": w[4], "bbox": list(w[:4])}
                for w in document[0].get_text("words")
            ]
            lines = original_heading_lines(document[0])
            caption = next(row for row in lines if row["text"] == "FIGURE 8A")
            label = next(row for row in lines if row["text"] == "Compound 062-C")
            self.assertIsNone(
                plot_axis_nomination(original, caption, label["bbox"], [540, 480])
            )
            blocks, sections = observe(document)
            self.assertEqual([row["cpd"] for row in blocks], ["Compound 062-C"])
            self.assertFalse(
                any(row["role"] == "figure_label_reference" for row in sections)
            )

    def test_invalid_caption_geometry_cannot_supply_a_source_cutoff(self):
        for box in (None, [], [0, 0, 0, 1], [0, 0, 5000, 10], [0, 0, float("nan"), 10]):
            with self.subTest(box=box):
                self.assertIsNone(
                    plot_axis_nomination(
                        [],
                        {"text": "Figure 8A", "bbox": box},
                        [50, 50, 150, 60],
                        [540, 480],
                    )
                )

    def test_saved_caption_and_actual_original_axis_strokes_still_replay(self):
        import fitz

        with plot_document() as document:
            self.outside_prose(document[0])
            blocks, sections = self.observe_with_controlled_axis_reader(document)
            self.assertEqual(blocks, [])
            proof = json.loads(json.dumps(sections[0]["heading_observation"]))
            self.assertEqual(original_plot_source_errors(document, [proof]), [])
            changed = copy.deepcopy(proof)
            changed["figure_source"]["caption"]["bbox"][1] -= 30
            self.assertIsNone(proved_heading_declaration(changed))
            document[0].draw_rect(
                fitz.Rect(180, 248, 195, 252), color=None, fill=(1, 1, 1)
            )
            self.assertTrue(original_plot_source_errors(document, [proof]))

    def test_binder_saved_web_catalog_and_model_plan_keep_the_figure_non_molecular(
        self,
    ):
        def extra_pages(document):
            with plot_document() as drawing:
                self.outside_prose(drawing[0], numbered=True)
                document.insert_pdf(drawing)

        with tempfile.TemporaryDirectory(prefix="figure-context-catalogue-") as root:
            root = Path(root)
            (root / "structures").mkdir()
            write_json_atomic(
                root / "structures/metadata.json",
                contracts.artifact_identity(
                    contracts.STRUCTURES_SCHEMA,
                    contracts.STRUCTURES_SCHEMA_VERSION,
                ),
            )
            pdf, _result, payload = self.observe_with_controlled_axis_reader(
                None,
                action=lambda: original_catalogue(
                    root,
                    root,
                    labels=("017B", "092C"),
                    identities=("first-drawing", "second-drawing"),
                    selected=False,
                    extra_pages=extra_pages,
                ),
            )
            payload = json.loads(json.dumps(payload))
            entries = payload["compound_catalog"]["entries"]
            self.assertEqual(
                [row["cpd"] for row in entries], ["Compound 017B", "Compound 092C"]
            )
            self.assertEqual(reference_issues(payload, entries), [])
            self.assertEqual(coverage_errors(payload), [])
            self.assertEqual(
                [row["cpd"] for row in read_compound_catalog(payload, entries)[0]],
                ["Compound 017B", "Compound 092C"],
            )
            plan = recognition_inputs(payload)
            self.assertEqual(len(plan.formal), 2)
            self.assertEqual(len(plan.plot_references), 1)
            import fitz

            with fitz.open(pdf) as original:
                self.assertEqual(
                    original_plot_source_errors(original, plan.plot_references), []
                )


if __name__ == "__main__":
    unittest.main()
