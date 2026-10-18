"""Original graphic/text separation, not textual prefix deletion or ID repair."""

import copy
import json
import unittest

from patent_sar_extractor.core.plot_legend_locator import (
    legend_candidate,
    locator_nomination,
    observe_legend_locator,
)
from tests.test_heading_source_ownership import PlotLegendHeadingTests


def source_line(text="-Compound 77A"):
    return {
        "text": text,
        "bbox": [307, 110, 411, 127],
        "source": "page_ocr",
        "geometry_space": "rendered",
    }


class LegendLocatorTests(unittest.TestCase):
    def test_original_whole_line_and_exact_literal_range_survive_round_trip(self):
        for raw in ("-Compound 77A", "→— Compound 77A", "Compound 77A"):
            with self.subTest(raw=raw), PlotLegendHeadingTests.document() as document:
                line = source_line(raw)
                before = copy.deepcopy(line)
                packet = observe_legend_locator(document[0], line, [520, 420])
                self.assertIsNotNone(packet)
                observed = locator_nomination(
                    json.loads(json.dumps(packet)), [520, 420]
                )
                self.assertEqual(observed["text"], "Compound 77A")
                self.assertGreater(observed["bbox"][0], line["bbox"][0])
                self.assertGreater(observed["bbox"][2] - observed["bbox"][0], 65)
                self.assertEqual(line, before)
                self.assertEqual(packet["source_line"], before)
                start, end = packet["literal_range"]
                self.assertEqual(raw[start:end], observed["text"])

    def test_no_key_or_a_known_synthesis_role_cannot_be_a_graphic_exemption(self):
        with PlotLegendHeadingTests.document(marker=False) as document:
            self.assertIsNone(
                observe_legend_locator(document[0], source_line(), [520, 420])
            )
        for raw in (
            "Synthesis of Compound 77A",
            "Preparation Compound 77A",
            "Compound 77A: Synthesis",
            "Compound 12 → Compound 77A",
            "-Compound 077B",
            "-Example 77A",
        ):
            with self.subTest(raw=raw):
                # 077B is a literal different identity, never repaired to77A.
                if raw == "-Compound 077B":
                    candidate = legend_candidate(raw)
                    self.assertEqual(candidate[2], "Compound 077B")
                else:
                    self.assertIsNone(legend_candidate(raw))

    def test_real_prefix_words_are_not_erased_as_if_they_were_a_key(self):
        with PlotLegendHeadingTests.document(marker=False) as document:
            document[0].insert_text((250, 122), "Control", fontsize=10)
            line = source_line("Control Compound 77A")
            line["bbox"][0] = 247
            self.assertIsNone(observe_legend_locator(document[0], line, [520, 420]))

    def test_pixels_ranges_geometry_and_unknown_fields_are_revalidated(self):
        with PlotLegendHeadingTests.document() as document:
            baseline = observe_legend_locator(document[0], source_line(), [520, 420])
        self.assertIsNotNone(locator_nomination(baseline, [520, 420]))
        for mutation in ("range", "bool", "source", "dpi", "pixels", "bbox", "extra"):
            with self.subTest(mutation=mutation):
                changed = copy.deepcopy(baseline)
                if mutation == "range":
                    changed["literal_range"][0] += 1
                elif mutation == "bool":
                    changed["literal_range"][0] = True
                elif mutation == "source":
                    changed["source_line"]["source"] = "model_guess"
                elif mutation == "dpi":
                    changed["pixels"]["readings"][0]["dpi"] = True
                elif mutation == "pixels":
                    changed["pixels"]["readings"][1]["mask_hex"] = "00"
                elif mutation == "bbox":
                    changed["source_line"]["bbox"][0] += 5
                else:
                    changed["accepted"] = True
                self.assertIsNone(locator_nomination(changed, [520, 420]))


if __name__ == "__main__":
    unittest.main()
