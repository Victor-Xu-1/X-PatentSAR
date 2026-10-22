"""Complete multi-row graphic keys must not become chemical declarations."""

import copy
import json
import unittest
from unittest.mock import patch

import fitz

from patent_sar_extractor.core.heading_evidence import original_heading_lines
from patent_sar_extractor.core.heading_source_proof import proved_heading_declaration
from patent_sar_extractor.core.plot_legend_locator import (
    locator_nomination,
    observe_legend_locator,
)
from patent_sar_extractor.core.plot_reference import observe_plot_reference
from patent_sar_extractor.core.plot_reference_proof import plot_reference_status
from tests.test_plot_reference_layout import plot_document


def two_row_plot(
    labels=("Compound 062-C", "Control"), *, axes=True, second_key=True, **layout
):
    document = plot_document(legend=labels[0], axes=axes, **layout)
    page = document[0]
    if second_key:
        page.draw_line((325, 132), (341, 132), width=1)
        page.draw_circle((333, 132), 2)
    page.insert_text((347, 135), labels[1], fontsize=9)
    return document


def nomination(lines, label):
    heading = next(row for row in lines if row["text"] == label)
    members = [
        row for row in lines if row["bbox"][0] >= 347 and 108 <= row["bbox"][1] <= 135
    ]
    return {
        **heading,
        "source": "page_ocr",
        "bbox": [
            min(row["bbox"][0] for row in members),
            min(row["bbox"][1] for row in members),
            max(row["bbox"][2] for row in members),
            max(row["bbox"][3] for row in members),
        ],
    }


def reference(document, *, coarse=False, label="Compound 062-C", source_lines=None):
    page = document[0]
    lines = source_lines if source_lines is not None else original_heading_lines(page)
    heading = (
        nomination(lines, label)
        if coarse
        else next(row for row in lines if row["text"] == label)
    )
    return observe_plot_reference(page, heading, lines, "a" * 64, cache={})


class PlotLegendRowTests(unittest.TestCase):
    def test_an_independent_control_row_does_not_change_a_precise_legend(self):
        with two_row_plot() as document:
            proof = reference(document)
        self.assertIsNotNone(proof)
        declared = proved_heading_declaration(proof)
        self.assertIsNotNone(declared)
        self.assertEqual(declared["role"], "figure_label_reference")

    def test_a_coarse_locator_keeps_both_original_rows_without_a_heading_error(self):
        with two_row_plot() as document:
            proof = reference(document, coarse=True)
        self.assertIsNotNone(proof)
        declared = proved_heading_declaration(proof)
        self.assertIsNotNone(declared)
        self.assertEqual(declared["role"], "figure_label_reference")
        restored = json.loads(json.dumps(proof))
        self.assertEqual(plot_reference_status(restored), plot_reference_status(proof))
        self.assertEqual(
            [row["text"] for row in restored["original_locator"]["rows"]],
            ["Compound 062-C", "Control"],
        )

    def test_selection_is_literal_not_first_top_or_a_fixed_identifier(self):
        for labels, target in (
            (("Control", "Compound 071-D"), "Compound 071-D"),
            (("Compound 062-C", "Compound 82A"), "Compound 82A"),
        ):
            with self.subTest(labels=labels), two_row_plot(labels) as document:
                proof = reference(document, coarse=True, label=target)
            self.assertIsNotNone(proved_heading_declaration(proof))
            self.assertEqual(proof["nomination"]["text"], target)
            self.assertEqual(
                [row["text"] for row in proof["original_locator"]["rows"]], list(labels)
            )

    def test_missing_keys_repeated_target_and_true_preparation_remain_unresolved(self):
        for options in (
            {"second_key": False},
            {"labels": ("Compound 062-C", "Compound 062-C")},
            {"labels": ("Compound 062-C", "Synthesis of Compound 82A")},
            {"labels": ("Compound 062-C", "Compound ?")},
            {"axes": False},
        ):
            with self.subTest(options=options), two_row_plot(**options) as document:
                proof = reference(document, coarse=True)
            self.assertIsNone(proved_heading_declaration(proof))

    def test_every_row_read_geometry_and_parent_inventory_are_mandatory(self):
        with two_row_plot() as document:
            baseline = reference(document, coarse=True)
        self.assertIsNotNone(proved_heading_declaration(baseline))
        for mutation in (
            "omit",
            "reverse",
            "text",
            "geometry",
            "key",
            "cell",
            "downgrade",
            "extra",
            "missing_origin",
        ):
            with self.subTest(mutation=mutation):
                changed = copy.deepcopy(baseline)
                locator = changed["original_locator"]
                if mutation == "omit":
                    locator["rows"].pop()
                elif mutation == "reverse":
                    locator["rows"].reverse()
                elif mutation == "text":
                    locator["rows"][1]["text"] = "Vehicle"
                elif mutation == "geometry":
                    locator["rows"][1]["bbox"][0] += 1
                elif mutation == "key":
                    locator["rows"][1]["key"][1] += 1
                elif mutation == "cell":
                    locator["rows"][1]["cell"]["reading"]["observations"] = []
                elif mutation == "downgrade":
                    changed["version"] = 6
                elif mutation == "missing_origin":
                    locator["rows"][1]["cell"]["sources"] = []
                else:
                    locator["selected"] = 0
                self.assertIsNone(proved_heading_declaration(changed))
                if mutation != "downgrade":
                    self.assertIsNone(locator_nomination(locator, [540, 480]))

    def test_the_full_physical_row_budget_refuses_before_any_text_recognition(self):
        with fitz.open() as document:
            page = document.new_page(width=540, height=480)
            for index in range(9):
                baseline = 120 + index * 3
                page.draw_line((325, baseline - 1), (341, baseline - 1), width=0.2)
                page.insert_text((347, baseline), f"Control {index}", fontsize=2)
            line = {
                "text": "Compound 31",
                "bbox": [347, 116, 400, 146],
                "source": "page_ocr",
                "geometry_space": "rendered",
            }
            with patch(
                "patent_sar_extractor.core.activity_grid_role_observation.get_ocr_engine",
                side_effect=AssertionError("Over-budget rows cannot request OCR"),
            ):
                self.assertIsNone(observe_legend_locator(page, line, [540, 480]))

    def test_actual_scanned_rows_use_the_same_complete_original_cell_reader(self):
        with (
            two_row_plot(y_values=("150", "100", "25"), middle_tick="10") as drawing,
            fitz.open() as scanned,
        ):
            lines = original_heading_lines(drawing[0])
            page = scanned.new_page(width=540, height=480)
            page.insert_image(
                page.rect, stream=drawing[0].get_pixmap(dpi=240).tobytes("png")
            )
            proof = reference(scanned, coarse=True, source_lines=lines)
        self.assertIsNotNone(proved_heading_declaration(proof))
        rows = proof["original_locator"]["rows"]
        self.assertEqual([row["text"] for row in rows], ["Compound 062-C", "Control"])
        self.assertTrue(
            all(len(row["cell"]["reading"]["rendered_frames"]) == 2 for row in rows)
        )

    def test_a_good_legend_cannot_waive_missing_original_scan_axis_strokes(self):
        # Numeric words without actual perpendicular original strokes cannot
        # establish a figure, even when every legend row can be read.
        with two_row_plot(axes=False) as drawing, fitz.open() as scanned:
            lines = original_heading_lines(drawing[0])
            page = scanned.new_page(width=540, height=480)
            page.insert_image(
                page.rect, stream=drawing[0].get_pixmap(dpi=240).tobytes("png")
            )
            locator = observe_legend_locator(
                page, nomination(lines, "Compound 062-C"), [540, 480]
            )
            self.assertIsNotNone(locator_nomination(locator, [540, 480]))
            self.assertIsNone(
                proved_heading_declaration(
                    reference(scanned, coarse=True, source_lines=lines)
                )
            )


if __name__ == "__main__":
    unittest.main()
