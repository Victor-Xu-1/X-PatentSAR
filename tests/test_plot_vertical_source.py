"""Complete small original y-axis words, not a successful numeric subset."""

import copy
import tempfile
import unittest
from pathlib import Path

from patent_sar_extractor.core.heading_source_proof import proved_heading_declaration
from patent_sar_extractor.core.plot_axis_words import refined_axis_tokens
from patent_sar_extractor.core.plot_reference_geometry import literal
from tests.test_plot_source_nomination import observe_plot


class VerticalPlotSourceTests(unittest.TestCase):
    def test_both_complete_axes_and_single_nomination_do_not_grant_missing_proof(self):
        with tempfile.TemporaryDirectory() as directory:
            _, sections = observe_plot(Path(directory), vertical_font_size=5.5)
        baseline = next(
            s["heading_observation"]
            for s in sections
            if s["role"] == "figure_label_reference"
        )
        self.assertIsNotNone(proved_heading_declaration(baseline))
        for mutation in (
            "omit_y",
            "omit_last_word",
            "reverse_y",
            "lane_bool",
            "lane_bounds",
            "frame_protocol",
            "nominal_dpi",
            "nominal_mask",
            "promote_nomination",
            "only_one_final_reading",
            "legacy_protocol",
            "word_scope",
            "word_confidence",
        ):
            changed = copy.deepcopy(baseline)
            figure = changed["figure_source"]
            refinement = figure["axis_refinement"]
            packet = refinement["word_observations"]["y"]
            row = packet["readings"][0]
            if mutation == "omit_y":
                refinement["word_observations"].pop("y")
            elif mutation == "omit_last_word":
                row["words"].pop()
            elif mutation == "reverse_y":
                row["words"].reverse()
            elif mutation == "lane_bool":
                row["frame"]["lane_bounds"][0] = True
            elif mutation == "lane_bounds":
                row["frame"]["lane_bounds"][0] -= 2
            elif mutation == "frame_protocol":
                row["frame"]["version"] = 1
            elif mutation == "nominal_dpi":
                refinement["axis_strokes"]["nominal_dpi"] = True
            elif mutation == "nominal_mask":
                refinement["axis_strokes"]["y"]["readings"][0]["mask_hex"] = "00"
            elif mutation == "promote_nomination":
                figure["axis_strokes"] = copy.deepcopy(refinement["axis_strokes"])
                figure["axis_strokes"].pop("nominal_dpi")
            elif mutation == "only_one_final_reading":
                figure["axis_strokes"]["y"]["readings"].pop()
            elif mutation == "legacy_protocol":
                changed["version"] = 5
            elif mutation == "word_scope":
                packet["bbox"][0] += 2
            else:
                row["words"][-1]["reading"]["confidence"] = 0.1
            changed["status"] = "confirmed"
            with self.subTest(mutation=mutation):
                self.assertIsNone(proved_heading_declaration(changed))
        self.assertIsNotNone(proved_heading_declaration(baseline))

    def test_agreeing_complete_reads_cannot_erase_a_qualified_original_conflict(self):
        bounds = [0, 0, 40, 80]
        parts = [{"text": "100", "bbox": [12, 20, 30, 31]}]
        for text, origin in (("10", "raster"), ("SL", "raster"), ("99", "native")):
            token = {
                "text": text,
                "bbox": [11, 19, 31, 32],
                "confidence": 0.99,
                "source": origin,
            }
            with self.subTest(text=text, origin=origin):
                source = copy.deepcopy(token)
                self.assertIsNone(refined_axis_tokens([token], [], parts, bounds))
                self.assertEqual(token, source)
        weak = {"text": "?", "bbox": [11, 19, 31, 32], "confidence": 0.1}
        elsewhere = {
            "text": "Compound 100",
            "bbox": [90, 90, 130, 105],
            "confidence": 1,
        }
        self.assertEqual(
            refined_axis_tokens([weak, elsewhere], [], parts, bounds),
            [elsewhere, *parts],
        )

    def test_small_vertical_words_are_observed_from_the_complete_original(self):
        for font in (5.5, 6):
            with self.subTest(font=font), tempfile.TemporaryDirectory() as directory:
                blocks, sections = observe_plot(
                    Path(directory), font_size=7, vertical_font_size=font
                )
                figures = [s for s in sections if s["role"] == "figure_label_reference"]
                self.assertEqual(
                    len(figures), 1, [(s["role"], s.get("line_text")) for s in sections]
                )
                self.assertEqual(blocks, [])
                self.assertIsNotNone(
                    proved_heading_declaration(figures[0]["heading_observation"])
                )
                self.assertEqual(
                    [
                        part["text"]
                        for part in figures[0]["heading_observation"]["figure_source"][
                            "axes"
                        ]["y"]
                    ],
                    ["150", "125", "100", "75", "50", "25", "0"],
                )

    def test_compound_prefix_spacing_does_not_change_a_complete_printed_id(self):
        for first, second in (
            ("Compound57", "Compound 57"),
            ("Cmpd. 57A", "Compound 57A"),
            ("compound:57", "Compound 57"),
        ):
            with self.subTest(first=first, second=second):
                self.assertEqual(literal(first), literal(second))
        for first, second in (
            ("Compound 057", "Compound 57"),
            ("Compound 57-A", "Compound 57A"),
            ("Compound 57 first eluting isomer", "Compound 57"),
            ("label-id:57", "Compound 57"),
            ("Example 57", "Compound 57"),
        ):
            with self.subTest(first=first, second=second):
                self.assertNotEqual(literal(first), literal(second))


if __name__ == "__main__":
    unittest.main()
