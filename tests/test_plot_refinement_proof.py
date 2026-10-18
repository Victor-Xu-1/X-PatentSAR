"""Full scanned source discovery and immutable refined-heading proof consumers."""

import copy
import json
import tempfile
import unittest
from pathlib import Path

import fitz

from patent_sar_extractor.core.binding_page_source import binding_page_source
from patent_sar_extractor.core.binding_source_headings import observed_heading_blocks
from patent_sar_extractor.core.binding_source_references import (
    reference_issues,
    reference_scope,
)
from patent_sar_extractor.core.heading_source_proof import proved_heading_declaration
from patent_sar_extractor.core.source_evidence_identity import proof_id
from patent_sar_extractor.core.table_geometry import page_tokens
from tests.test_plot_reference_layout import plot_document


def scanned_sections(angle=45, *, hidden_label=None):
    with (
        tempfile.TemporaryDirectory(prefix="plot-original-") as directory,
        plot_document(angle) as original,
        fitz.open() as scanned,
    ):
        page = scanned.new_page(width=540, height=480)
        page.insert_image(
            page.rect,
            stream=original[0].get_pixmap(matrix=fitz.Matrix(3, 3)).tobytes("png"),
        )
        if hidden_label is not None:
            page.insert_text((347, 119), hidden_label, fontsize=10, render_mode=3)
        source = Path(directory) / "original.pdf"
        scanned.save(source)
        with fitz.open(source) as document:
            _, original_lines = binding_page_source(
                document, str(source), Path(directory) / "raw.json", 1, {}
            )
            sections = []
            blocks = observed_heading_blocks(
                document,
                [0],
                {},
                source_sections=sections,
                source_regions={0: []},
                source_line_map=original_lines,
                tokens_for_page=lambda page: page_tokens(
                    page, dpi=300, allow_tesseract=False
                ),
            )
        return blocks, json.loads(json.dumps(sections))


class PlotRefinementProofTests(unittest.TestCase):
    def test_shared_observer_native_identifier_conflict_cannot_be_waived_by_a_key(self):
        blocks, sections = scanned_sections(hidden_label="Compound 63")
        self.assertTrue(blocks or sections)
        self.assertTrue(
            all(section["role"] != "figure_label_reference" for section in sections)
        )
        self.assertTrue(
            all(
                proved_heading_declaration(section["heading_observation"]) is None
                for section in sections
            )
        )

    def test_actual_scanned_discovery_without_injected_headings_round_trips(self):
        for angle in (45, 90):
            with self.subTest(angle=angle):
                blocks, sections = scanned_sections(angle)
                self.assertEqual(blocks, [])
                self.assertEqual(len(sections), 1)
                proof = sections[0]["heading_observation"]
                self.assertEqual(proof["version"], 6)
                self.assertIn("original_locator", proof)
                if proof["original_locator"] is not None:
                    locator = proof["original_locator"]
                    start, end = locator["literal_range"]
                    self.assertEqual(
                        locator["source_line"]["text"][start:end],
                        proof["nomination"]["text"],
                    )
                self.assertIsNotNone(proved_heading_declaration(proof))
                refinement = proof["figure_source"]["axis_refinement"]
                self.assertIsNotNone(refinement)
                self.assertEqual(
                    refinement["word_observations"]["x"]["bbox"][::2], [0, 540]
                )
                self.assertLess(len(json.dumps(sections[0])), 1024 * 1024)
                self.assertEqual(len(proof_id(sections[0])), 64)
                payload = {
                    "source_sections": sections,
                    "source_reference_scope": reference_scope(sections),
                }
                self.assertEqual(reference_issues(payload, []), [])

    def test_omitted_pixels_words_views_coordinates_and_unknown_fields_never_replay(
        self,
    ):
        blocks, sections = scanned_sections()
        self.assertEqual(blocks, [])
        self.assertEqual(len(sections), 1)
        baseline = sections[0]["heading_observation"]
        self.assertIsNotNone(proved_heading_declaration(baseline))
        for mutation in (
            "omit_word",
            "word_order",
            "angle",
            "view_sha",
            "view_space",
            "view_text",
            "word_box",
            "dpi",
            "mask",
            "row_extent",
            "nomination",
            "extra_field",
            "old_version",
            "locator_missing",
            "locator_range",
            "locator_pixels",
            "locator_id",
        ):
            with self.subTest(mutation=mutation):
                changed = copy.deepcopy(baseline)
                refinement = changed["figure_source"]["axis_refinement"]
                packet = refinement["word_observations"]["x"]
                row = packet["readings"][0]
                word = row["words"][0]
                if mutation == "omit_word":
                    row["words"].pop()
                elif mutation == "word_order":
                    row["words"].reverse()
                elif mutation == "angle":
                    row["frame"]["angle"] += 90
                elif mutation == "view_sha":
                    word["view_sha256"] = "f" * 64
                elif mutation == "view_space":
                    word["reading"]["coordinate_space"] = "original_pdf_points"
                elif mutation == "view_text":
                    word["reading"]["raw_text"] = "1000"
                elif mutation == "word_box":
                    word["bbox"][0] = True
                elif mutation == "dpi":
                    row["dpi"] = True
                elif mutation == "mask":
                    packet["pixels"]["readings"][0]["mask_hex"] = "00"
                elif mutation == "row_extent":
                    packet["bbox"][2] -= 20
                elif mutation == "nomination":
                    refinement["nomination"]["x"].pop()
                elif mutation == "extra_field":
                    packet["accepted"] = True
                elif mutation == "locator_missing":
                    changed.pop("original_locator")
                elif mutation == "locator_range":
                    changed["original_locator"]["literal_range"][0] = True
                elif mutation == "locator_pixels":
                    changed["original_locator"]["pixels"]["readings"][0]["mask_hex"] = (
                        "00"
                    )
                elif mutation == "locator_id":
                    changed["original_locator"]["source_line"]["text"] = (
                        "-Compound 063-C"
                    )
                else:
                    changed["version"] = 2
                changed["status"] = "confirmed"
                self.assertIsNone(proved_heading_declaration(changed))
        self.assertIsNotNone(proved_heading_declaration(baseline))


if __name__ == "__main__":
    unittest.main()
