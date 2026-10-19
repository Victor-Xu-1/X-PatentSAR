"""Dense original graph axes must not depend on coarse numeric token recall."""

import copy
import hashlib
import json
import tempfile
import unittest
from decimal import localcontext
from pathlib import Path

import fitz

from patent_sar_extractor.application.binding_policy import _binding_acceptance_errors
from patent_sar_extractor.core.binding_page_source import binding_page_source
from patent_sar_extractor.core.binding_source_headings import observed_heading_blocks
from patent_sar_extractor.core.binding_source_references import (
    reference_issues,
    reference_scope,
)
from patent_sar_extractor.core.formal_structure import coverage_errors
from patent_sar_extractor.core.heading_source_proof import proved_heading_declaration
from patent_sar_extractor.core.ocsr.recognition_inputs import recognition_inputs
from patent_sar_extractor.core.plot_reference_geometry import (
    axis_bounds,
    literal,
    plot_axes,
    plot_axis_nomination,
    tick_value,
)
from patent_sar_extractor.core.plot_reference_proof import plot_reference_status
from patent_sar_extractor.core.table_geometry import page_tokens
from patent_sar_extractor.web.compound_catalog import read_compound_catalog
from tests.test_heading_ruled_binding import run_original


def dose_plot(
    directory,
    *,
    font_size=7,
    vertical_font_size=None,
    angle=45,
    axes=True,
    unknown_tick=False,
    legend="Compound 57",
):
    """New controlled raster, not a private figure or extracted measurements."""
    path = directory / "original.pdf"
    with fitz.open() as drawing, fitz.open() as scanned:
        page = drawing.new_page(width=580, height=430)
        if axes:
            page.draw_line((130, 70), (130, 260), width=0.8)
            page.draw_line((130, 260), (380, 260), width=0.8)
        values = ["0.00001", "0.0001", "0.001", "0.01", "0.1", "1", "10", "100", "1000"]
        if unknown_tick:
            values[4] = "n/a"
        for index, value in enumerate(values):
            origin = fitz.Point(130 + index * 30, 300)
            page.insert_text(
                origin, value, fontsize=font_size, morph=(origin, fitz.Matrix(angle))
            )
        for index, value in enumerate(("150", "125", "100", "75", "50", "25", "0")):
            page.insert_text(
                (106, 90 + index * 26),
                value,
                fontsize=font_size
                if vertical_font_size is None
                else vertical_font_size,
            )
        page.draw_polyline(
            [
                (140, 100),
                (175, 105),
                (205, 120),
                (235, 180),
                (265, 215),
                (300, 240),
                (350, 245),
            ]
        )
        page.draw_line((398, 101), (414, 101), width=1)
        page.draw_circle((406, 101), 2, fill=(0, 0, 0))
        page.insert_text((420, 104), legend, fontsize=9)
        page.insert_text((220, 385), "FIG. 9B", fontsize=10)
        target = scanned.new_page(width=580, height=430)
        target.insert_image(target.rect, stream=page.get_pixmap(dpi=240).tobytes("png"))
        scanned.save(path)
    return path


def observe_plot(directory, **layout):
    original = dose_plot(directory, **layout)
    digest = hashlib.sha256(original.read_bytes()).hexdigest()
    with fitz.open(original) as document:
        _, lines = binding_page_source(
            document, str(original), directory / "raw.json", 1, {}
        )
        sections = []
        blocks = observed_heading_blocks(
            document,
            [0],
            {},
            source_sections=sections,
            source_regions={0: []},
            source_line_map=lines,
            tokens_for_page=lambda page: page_tokens(
                page, dpi=200, allow_tesseract=False
            ),
        )
    assert hashlib.sha256(original.read_bytes()).hexdigest() == digest
    return blocks, json.loads(json.dumps(sections))


class PhysicalPlotNominationTests(unittest.TestCase):
    def test_mixed_original_reaches_actual_binder_writer_and_current_consumers(self):
        for legend in ("Compound 57", "Compound 82A"):
            with (
                self.subTest(legend=legend),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                plot_root = root / "plot"
                plot_root.mkdir()
                original = dose_plot(plot_root, font_size=8.5, angle=-45, legend=legend)
                result, payload = run_original(root, raster=False, extra_pdf=original)
                self.assertEqual(result["bound"], 1)
                self.assertEqual(payload["source_issues"], [])
                self.assertEqual(_binding_acceptance_errors(payload), [])
                self.assertEqual(coverage_errors(payload), [])
                entries, _ = read_compound_catalog(
                    payload, payload["compound_catalog"]["entries"]
                )
                self.assertEqual([entry["cpd"] for entry in entries], ["Compound 82A"])
                self.assertEqual(
                    [entry["cpd"] for entry in recognition_inputs(payload).formal],
                    ["Compound 82A"],
                )
                figures = [
                    section
                    for section in payload["source_sections"]
                    if section["role"] == "figure_label_reference"
                ]
                self.assertEqual(len(figures), 1)
                self.assertEqual(figures[0]["heading_observation"]["version"], 6)

    def test_refined_anchor_and_all_original_words_are_mandatory_in_saved_proof(self):
        with tempfile.TemporaryDirectory() as directory:
            blocks, sections = observe_plot(Path(directory), font_size=8.5, angle=-45)
        self.assertEqual(blocks, [])
        baseline = next(
            section["heading_observation"]
            for section in sections
            if section["role"] == "figure_label_reference"
        )
        self.assertEqual(baseline["version"], 6)
        self.assertIsNotNone(proved_heading_declaration(baseline))
        for mutation in (
            "missing_anchor",
            "changed_nomination",
            "missing_anchor_mask",
            "moved_final_band",
            "cut_final_extent",
            "missing_word",
            "extra_axis_field",
            "changed_literal_owner",
            "old_protocol",
        ):
            changed = copy.deepcopy(baseline)
            figure = changed["figure_source"]
            refinement = figure["axis_refinement"]
            if mutation == "missing_anchor":
                refinement["axis_strokes"] = None
            elif mutation == "changed_nomination":
                refinement["nomination"]["x"].pop()
            elif mutation == "missing_anchor_mask":
                refinement["axis_strokes"]["x"]["readings"].pop()
            elif mutation == "moved_final_band":
                figure["axis_strokes"]["x"]["bbox"][1] += 5
            elif mutation == "cut_final_extent":
                figure["axis_strokes"]["x"]["bbox"][2] -= 10
            elif mutation == "missing_word":
                refinement["word_observations"]["x"]["readings"][0]["words"].pop()
            elif mutation == "extra_axis_field":
                figure["axis_strokes"]["accepted"] = True
            elif mutation == "changed_literal_owner":
                changed["nomination"]["text"] = "Compound 58"
            else:
                changed["version"] = 4
            changed["status"] = "confirmed"
            with self.subTest(mutation=mutation):
                self.assertIsNone(proved_heading_declaration(changed))
        for version in (True, 6.0, "6", [], {}):
            changed = {**baseline, "version": version, "status": "confirmed"}
            with self.subTest(version=version):
                self.assertEqual(plot_reference_status(changed), ("invalid", None))
        self.assertIsNotNone(proved_heading_declaration(baseline))

    def test_axis_stroke_windows_keep_full_outer_word_extents_not_their_centres(self):
        axes = {
            "x": [
                {"text": "0.00001", "bbox": [126, 296, 155, 322]},
                {"text": "1", "bbox": [280, 296, 287, 303]},
                {"text": "1000", "bbox": [371, 296, 387, 312]},
            ],
            "y": [
                {"text": "150", "bbox": [106, 82, 122, 93]},
                {"text": "75", "bbox": [106, 160, 118, 171]},
                {"text": "0", "bbox": [106, 238, 112, 249]},
            ],
        }
        windows = axis_bounds(axes)
        self.assertLessEqual(windows["x"][0], axes["x"][0]["bbox"][0])
        self.assertGreaterEqual(windows["x"][2], axes["x"][-1]["bbox"][2])
        self.assertGreaterEqual(windows["y"][2], axes["x"][0]["bbox"][2])

    def test_partial_coarse_row_can_nominate_but_cannot_prove_complete_axes(self):
        tokens = [
            {"text": text, "bbox": [78, y, 91, y + 10]}
            for text, y in (("90", 98), ("45", 158), ("0", 218))
        ] + [
            {"text": text, "bbox": [x, 280, x + 25, 292]}
            for text, x in (("0.001", 110), ("0.1", 170), ("1", 230))
        ]
        caption = {"text": "Figure 9", "bbox": [185, 365, 250, 377]}
        legend = [347, 105, 425, 120]
        self.assertIsNotNone(plot_axis_nomination(tokens, caption, legend, [540, 480]))
        self.assertIsNone(plot_axes(tokens, caption, legend, [540, 480]))

    def test_exact_numeric_tick_spellings_share_one_axis_identity_only(self):
        for first, second in (
            (".00001", "0.0000100"),
            ("1e-5", "0.00001"),
            ("-0.00", "0"),
            ("50.00%", "050%"),
        ):
            with self.subTest(first=first, second=second):
                self.assertEqual(literal(first), literal(second))
        for first, second in (
            ("1e-5", "1e-4"),
            ("1", "-1"),
            ("0.5%", "0.5"),
            ("Compound 007", "Compound 7"),
            ("0.1 nM", "0.1 uM"),
            ("n/a", "0"),
            ("NaN", "0"),
            ("1,000", "1000"),
            ("number:1e-5", "0.00001"),
            ("figure:9b", "Fig. 9B"),
            ("text:0.1", "0.1"),
        ):
            with self.subTest(first=first, second=second):
                self.assertNotEqual(literal(first), literal(second))

    def test_finite_axis_order_cannot_underflow_into_a_fabricated_zero(self):
        self.assertGreater(tick_value("1e-999"), 0)
        self.assertLess(tick_value("-1e-999"), 0)
        self.assertIsNone(tick_value("NaN"))
        self.assertIsNone(tick_value("1e9999"))

    def test_axis_keys_do_not_borrow_the_callers_decimal_rounding_context(self):
        with localcontext() as context:
            context.prec = 6
            self.assertEqual(
                literal("12345678901234567890.000"), literal("12345678901234567890")
            )
            self.assertNotEqual(
                literal("12345678901234567890"), literal("12345678901234567891")
            )

    def test_dense_oblique_log_ticks_reach_original_figure_proof(self):
        for size, angle in ((7, 45), (8.5, -45)):
            with (
                self.subTest(size=size, angle=angle),
                tempfile.TemporaryDirectory() as directory,
            ):
                blocks, sections = observe_plot(
                    Path(directory), font_size=size, angle=angle
                )
                figures = [
                    section
                    for section in sections
                    if section["role"] == "figure_label_reference"
                ]
                self.assertEqual(
                    len(figures), 1, [(s["role"], s.get("line_text")) for s in sections]
                )
                self.assertEqual(blocks, [])
                proof = figures[0]["heading_observation"]
                self.assertIsNotNone(proved_heading_declaration(proof))
                payload = {
                    "source_sections": sections,
                    "source_reference_scope": reference_scope(sections),
                }
                self.assertEqual(reference_issues(payload, []), [])

    def test_figure_words_and_numeric_rows_without_axes_do_not_exclude_a_source(self):
        with tempfile.TemporaryDirectory() as directory:
            blocks, sections = observe_plot(Path(directory), axes=False)
        self.assertTrue(blocks or sections)
        self.assertFalse(
            any(section["role"] == "figure_label_reference" for section in sections)
        )

    def test_unknown_original_tick_is_not_replaced_with_an_ordered_number(self):
        with tempfile.TemporaryDirectory() as directory:
            blocks, sections = observe_plot(Path(directory), unknown_tick=True)
        self.assertTrue(blocks or sections)
        self.assertFalse(
            any(section["role"] == "figure_label_reference" for section in sections)
        )


if __name__ == "__main__":
    unittest.main()
