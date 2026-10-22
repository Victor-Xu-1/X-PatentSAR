"""Differing original plot layouts through the shared heading/source ledger."""

import json
import unittest

import fitz

from patent_sar_extractor.core.binding_source_headings import observed_heading_blocks
from patent_sar_extractor.core.binding_source_references import (
    reference_issues,
    reference_scope,
)
from patent_sar_extractor.core.heading_evidence import original_heading_lines
from patent_sar_extractor.core.heading_source_proof import proved_heading_declaration
from patent_sar_extractor.core.plot_reference_geometry import figure_caption, plot_axes
from patent_sar_extractor.core.source_geometry import source_layout
from patent_sar_extractor.core.table_geometry import page_tokens


def plot_document(
    angle=0,
    *,
    axes=True,
    extra_tick=None,
    extra_y=None,
    synthesis=False,
    last_tick="100",
    legend_x=347,
    legend="Compound 062-C",
    y_values=("90", "45", "0"),
    middle_tick="1",
):
    """Synthetic source geometry only, without private patent content."""
    document = fitz.open()
    page = document.new_page(width=540, height=480)
    if axes:
        page.draw_line((110, 80), (110, 250), width=0.8)
        page.draw_line((110, 250), (300, 250), width=0.8)
    for x, value in zip((110, 170, 230, 290), ("0.001", "0.1", middle_tick, last_tick)):
        origin = fitz.Point(x, 295)
        page.insert_text(origin, value, fontsize=9, morph=(origin, fitz.Matrix(angle)))
    if extra_tick:
        origin = fitz.Point(260, 295)
        page.insert_text(
            origin, extra_tick, fontsize=9, morph=(origin, fitz.Matrix(angle))
        )
    for y, value in zip((105, 165, 225), y_values):
        page.insert_text((78, y + 3), value, fontsize=9)
    if extra_y:
        page.insert_text((78, 198), extra_y, fontsize=9)
    page.draw_line((legend_x - 22, 116), (legend_x - 6, 116), width=1)
    page.draw_circle((legend_x - 14, 116), 2, fill=(0, 0, 0))
    page.insert_text((legend_x, 119), legend, fontsize=10)
    page.insert_text((185, 365), "FIGURE 8A", fontsize=10)
    if synthesis:
        page.insert_text((54, 415), "Compound 29: Synthesis", fontsize=11)
    return document


def observe(document):
    sections = []
    blocks = observed_heading_blocks(
        document, [0], {}, source_sections=sections, source_regions={0: []}
    )
    return blocks, json.loads(json.dumps(sections))


class PlotLayoutTests(unittest.TestCase):
    def test_unaligned_unread_ink_inside_the_numeric_envelope_remains_a_veto(self):
        with plot_document() as baseline:
            blocks, sections = observe(baseline)
            self.assertEqual(blocks, [], sections)
            self.assertEqual(sections[0]["role"], "figure_label_reference")
        for value in ("n/a", "7"):
            with self.subTest(value=value), plot_document() as document:
                document[0].insert_text((260, 285), value, fontsize=9)
                blocks, sections = observe(document)
                self.assertEqual([b["cpd"] for b in blocks], ["Compound 062-C"])
                self.assertTrue(
                    all(s["role"] != "figure_label_reference" for s in sections)
                )

    def test_unread_outer_y_member_stays_in_the_original_axis_column(self):
        with plot_document() as baseline:
            blocks, sections = observe(baseline)
            self.assertEqual(blocks, [], sections)
            self.assertEqual(sections[0]["role"], "figure_label_reference")
        for value in ("n/a", "7x", "?"):
            with self.subTest(value=value), plot_document() as document:
                document[0].insert_text((78, 244), value, fontsize=9)
                blocks, sections = observe(document)
                self.assertEqual([b["cpd"] for b in blocks], ["Compound 062-C"])
                self.assertTrue(
                    all(s["role"] != "figure_label_reference" for s in sections)
                )

    def test_unaligned_original_note_does_not_poison_a_complete_axis(self):
        with plot_document(legend_x=250) as document:
            document[0].insert_text((460, 440), "n/a", fontsize=9)
            blocks, sections = observe(document)
            self.assertEqual(blocks, [], sections)
            self.assertEqual(sections[0]["role"], "figure_label_reference")

    def test_independent_outer_member_vetoes_an_incomplete_primary_numeric_row(self):
        with plot_document(legend_x=250, last_tick="n/a") as document:
            lines = original_heading_lines(document[0])
            label = next(line for line in lines if line["text"].startswith("Compound"))
            caption = next(line for line in lines if figure_caption(line["text"]))
            original = source_layout(document[0]).native
            primary = [token for token in original if token["text"] != "n/a"]
            self.assertIsNotNone(plot_axes(primary, caption, label["bbox"], [540, 480]))
            self.assertIsNone(
                plot_axes(
                    primary,
                    caption,
                    label["bbox"],
                    [540, 480],
                    independent_tokens=original,
                )
            )

    def test_unread_outer_tick_cannot_be_removed_by_a_shorter_numeric_envelope(self):
        with plot_document(legend_x=250) as baseline:
            blocks, sections = observe(baseline)
            self.assertEqual(blocks, [], sections)
            self.assertEqual(sections[0]["role"], "figure_label_reference")
        for last_tick in ("n/a", "7x", "?"):
            with (
                self.subTest(last_tick=last_tick),
                plot_document(legend_x=250, last_tick=last_tick) as document,
            ):
                blocks, sections = observe(document)
                self.assertEqual([b["cpd"] for b in blocks], ["Compound 062-C"])
                self.assertTrue(
                    all(s["role"] != "figure_label_reference" for s in sections)
                )

    def test_independent_native_axis_addition_vetoes_an_otherwise_qualified_plot(self):
        with plot_document(45) as document:
            page = document[0]
            lines = original_heading_lines(page)
            label = next(line for line in lines if line["text"].startswith("Compound"))
            caption = next(line for line in lines if figure_caption(line["text"]))
            tokens = source_layout(page).native
            self.assertIsNotNone(plot_axes(tokens, caption, label["bbox"], [540, 480]))
            shadow = [{"text": "n/a", "bbox": [259, 285, 272, 298]}]
            self.assertIsNone(
                plot_axes(
                    tokens,
                    caption,
                    label["bbox"],
                    [540, 480],
                    independent_tokens=shadow,
                )
            )

    def test_rotated_native_tick_labels_preserve_the_literal_figure_reference(self):
        for angle in (0, 45, 90, -45):
            with self.subTest(angle=angle), plot_document(angle) as document:
                blocks, sections = observe(document)
                self.assertEqual(blocks, [], sections)
                self.assertEqual(len(sections), 1)
                self.assertEqual(sections[0]["role"], "figure_label_reference")
                self.assertEqual(sections[0]["line_text"], "Compound 062-C")
                self.assertEqual(
                    [
                        p["text"]
                        for p in sections[0]["heading_observation"]["figure_source"][
                            "axes"
                        ]["x"]
                    ],
                    ["0.001", "0.1", "1", "100"],
                )
                self.assertIsNotNone(
                    proved_heading_declaration(sections[0]["heading_observation"])
                )
                payload = {
                    "source_sections": sections,
                    "source_reference_scope": reference_scope(sections),
                }
                self.assertEqual(reference_issues(payload, []), [])

    def test_rotated_labels_without_actual_axes_never_close_structure_obligations(self):
        for angle in (45, 90):
            with (
                self.subTest(angle=angle),
                plot_document(angle, axes=False) as document,
            ):
                blocks, sections = observe(document)
                self.assertEqual([b["cpd"] for b in blocks], ["Compound 062-C"])
                self.assertTrue(
                    all(s["role"] != "figure_label_reference" for s in sections)
                )

    def test_a_conflicting_or_unread_tick_cannot_be_silently_dropped(self):
        for angle in (0, 45, 90):
            for value in ("0.01", "7x", "?"):
                with (
                    self.subTest(angle=angle, value=value),
                    plot_document(angle, extra_tick=value) as document,
                ):
                    blocks, sections = observe(document)
                    self.assertEqual([b["cpd"] for b in blocks], ["Compound 062-C"])
                    self.assertTrue(
                        all(s["role"] != "figure_label_reference" for s in sections)
                    )

    def test_the_complete_y_axis_keeps_conflicting_and_unread_members(self):
        for value in ("60", "n/a"):
            with (
                self.subTest(value=value),
                plot_document(45, extra_y=value) as document,
            ):
                blocks, sections = observe(document)
                self.assertEqual([b["cpd"] for b in blocks], ["Compound 062-C"])
                self.assertTrue(
                    all(s["role"] != "figure_label_reference" for s in sections)
                )

    def test_nearby_real_synthesis_remains_an_independent_missing_original(self):
        with plot_document(45, synthesis=True) as document:
            blocks, sections = observe(document)
        self.assertEqual([b["cpd"] for b in blocks], ["Compound 29"])
        payload = {
            "source_sections": sections,
            "source_reference_scope": reference_scope(sections),
        }
        self.assertEqual(
            [p["cpd"] for p in reference_issues(payload, [])], ["Compound 29"]
        )

    def test_original_scanned_rotated_labels_use_the_existing_ocr_and_saved_replay(
        self,
    ):
        for angle in (45, 90):
            with (
                self.subTest(angle=angle),
                plot_document(angle) as original,
                fitz.open() as scanned,
            ):
                lines = [
                    {**line, "source": "page_ocr"}
                    for line in original_heading_lines(original[0])
                ]
                page = scanned.new_page(width=540, height=480)
                page.insert_image(
                    page.rect,
                    stream=original[0]
                    .get_pixmap(matrix=fitz.Matrix(3, 3))
                    .tobytes("png"),
                )
                sections = []
                blocks = observed_heading_blocks(
                    scanned,
                    [0],
                    {},
                    source_sections=sections,
                    source_regions={0: []},
                    source_line_map={0: lines},
                    tokens_for_page=lambda page: page_tokens(
                        page, dpi=300, allow_tesseract=False
                    ),
                )
                self.assertEqual([b["cpd"] for b in blocks], [])
                self.assertEqual(sections[0]["role"], "figure_label_reference")
                proof = json.loads(json.dumps(sections[0]["heading_observation"]))
                self.assertIsNotNone(proved_heading_declaration(proof))
                payload = {
                    "source_sections": sections,
                    "source_reference_scope": reference_scope(sections),
                }
                self.assertEqual(reference_issues(payload, []), [])

    def test_independent_native_unknown_inside_the_axis_is_not_dropped_by_raster(self):
        with plot_document(45) as original, fitz.open() as scanned:
            lines = [
                {**line, "source": "page_ocr"}
                for line in original_heading_lines(original[0])
            ]
            page = scanned.new_page(width=540, height=480)
            page.insert_image(
                page.rect,
                stream=original[0].get_pixmap(matrix=fitz.Matrix(3, 3)).tobytes("png"),
            )
            page.insert_text((260, 292), "n/a", fontsize=9, render_mode=3)
            sections = []
            blocks = observed_heading_blocks(
                scanned,
                [0],
                {},
                source_sections=sections,
                source_regions={0: []},
                source_line_map={0: lines},
                tokens_for_page=lambda page: page_tokens(
                    page, dpi=300, allow_tesseract=False
                ),
            )
        self.assertEqual([b["cpd"] for b in blocks], ["Compound 062-C"])
        self.assertTrue(all(s["role"] != "figure_label_reference" for s in sections))


if __name__ == "__main__":
    unittest.main()
