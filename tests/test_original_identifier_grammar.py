"""Complete literal IDs across original source readers, not patent-specific data."""

import unittest
from unittest.mock import patch

import fitz
from unruled_structure_support import UnruledStructureControls

from patent_sar_extractor.core.activity_identity import normalize_compound
from patent_sar_extractor.core.activity_join import (
    activity_for_compound,
    activity_order_and_map,
)
from patent_sar_extractor.core.activity_result_references import _observed
from patent_sar_extractor.core.binding_labels import _labels_from_ocr_text
from patent_sar_extractor.core.binding_source_headings import observed_heading_blocks
from patent_sar_extractor.core.cell_identity_proof import confirmed_identity_readings
from patent_sar_extractor.core.cell_ocr_observation import OCRObservation
from patent_sar_extractor.core.compound_caption import caption_identity
from patent_sar_extractor.core.numbered_structure_binding import bind_numbered_tables
from patent_sar_extractor.core.numbered_structure_pairs import _label
from patent_sar_extractor.core.pipeline_rules import annotate_binding_accuracy
from patent_sar_extractor.core.source_section_roles import (
    nonfinal_original_label,
    section_heading,
)
from patent_sar_extractor.core.table_cells import _normalize, read_cell
from patent_sar_extractor.core.visible_structure_binding import bind_visible_captions


class OriginalIdentifierGrammarTests(UnruledStructureControls, unittest.TestCase):
    def test_series_prefix_is_not_an_intermediate_role_and_original_namespace_is_preserved(
        self,
    ):
        for raw in (
            "Compound I-73",
            "Compound Intermediate-73",
            "Example 73: Synthesis of Compound 14 using Intermediate 7",
        ):
            with self.subTest(raw=raw):
                self.assertFalse(nonfinal_original_label(raw))
        self.assertTrue(nonfinal_original_label("中间体73"))

    def test_native_nonfinal_role_blocks_the_raster_fast_path_and_saved_packet(self):
        tokens = [{"text": "Compound 73", "x": 20, "y": 10}]
        with (
            patch(
                "patent_sar_extractor.core.table_cells.native_cell_text",
                return_value="Intermediate 73",
            ),
            patch(
                "patent_sar_extractor.core.table_cells._ocr_cell",
                return_value=OCRObservation("73", 0.99, "Compound 73"),
            ),
        ):
            result = read_cell(None, (0, 0, 100, 30), tokens, "label", False)
        self.assertTrue(result.needs_review)
        self.assertEqual(result.value, "")
        self.assertTrue(
            any(o["text"] == "Intermediate 73" for o in result.observations)
        )
        bounds = [0, 0, 100, 30]
        packets = [
            {"method": "native_cell", "text": "Intermediate 73"},
            *[
                {
                    "method": f"cell_ocr_{dpi}dpi",
                    "text": "73",
                    "confidence": 0.99,
                    "bbox": bounds,
                    "coordinate_space": "original_pdf_points",
                }
                for dpi in (400, 600)
            ],
        ]
        self.assertFalse(confirmed_identity_readings("73", packets))
        self.assertFalse(
            _observed({"value": "73", "bbox": bounds, "observations": packets}, True)
        )

    def test_rereads_cannot_turn_an_original_intermediate_or_assay_title_into_a_final_id(
        self,
    ):
        for raw in (
            "Intermediate 73",
            "Intermediate-73",
            "Example 73: Cell proliferation assay",
        ):
            tokens = [{"text": raw, "x": 20, "y": 10}]
            with (
                self.subTest(raw=raw),
                patch(
                    "patent_sar_extractor.core.table_cells._ocr_cell",
                    return_value=OCRObservation("73", 0.99, "Compound 73"),
                ),
            ):
                result = read_cell(None, (0, 0, 100, 30), tokens, "label", False)
                self.assertTrue(result.needs_review)
                self.assertEqual(result.value, "")
                self.assertEqual(result.observations[0]["text"], raw)

    def test_original_intermediate_headings_are_recorded_not_published_as_compounds(
        self,
    ):
        with fitz.open() as doc:
            page = doc.new_page()
            page.insert_text((50, 70), "Compound 10000: Synthesis")
            page.insert_text((50, 120), "Intermediate I-73: Synthesis")
            page.insert_text((50, 170), "Example 95: Preparation of Intermediate 7")
            page.insert_text(
                (50, 220), "Example 96: Synthesis of Compound 14 using Intermediate 7"
            )
            sections = []
            blocks = observed_heading_blocks(doc, [0], {}, source_sections=sections)
        self.assertEqual([b["cpd"] for b in blocks], ["Compound 10000", "Compound 96"])
        self.assertEqual(
            [s["role"] for s in sections],
            [
                "compound_heading",
                "intermediate_section",
                "intermediate_section",
                "compound_heading",
            ],
        )

    def test_two_matching_rereads_cannot_merge_ambiguous_original_id_tokens(self):
        bounds = (0, 0, 100, 30)
        for raw, candidate in (("1 2", "12"), ("44 A", "44A"), ("Compound 1 2", "12")):
            kind = "label" if raw.startswith("Compound") else "id"
            tokens = [{"text": raw, "x": 20, "y": 10}]
            with (
                self.subTest(raw=raw),
                patch(
                    "patent_sar_extractor.core.table_cells._ocr_cell",
                    return_value=OCRObservation(candidate, 0.99, candidate),
                ),
            ):
                observed = read_cell(None, bounds, tokens, kind, False)
                self.assertTrue(observed.needs_review)
                self.assertEqual(observed.value, "")

    def test_superscripts_are_not_invented_digits_and_fullwidth_ids_keep_raw_typography(
        self,
    ):
        self.assertIsNone(section_heading("Compound 12³: Synthesis"))
        self.assertEqual(
            section_heading("Compound １２Ａ: Synthesis")["identifier"], "12A"
        )
        self.assertEqual(caption_identity("Compound １２Ａ")[0], "12A")
        self.assertEqual(_normalize("１２Ａ", "id"), "12A")

    def test_visible_text_never_clips_a_series_prefix_or_matches_a_decimal_fragment(
        self,
    ):
        for raw in ("I-44A", "A-001B", "10000AB", "1-2-3AB"):
            with self.subTest(raw=raw):
                self.assertEqual(_labels_from_ocr_text("Compound " + raw), [raw])
        self.assertEqual(_labels_from_ocr_text("125.34 or source-hash:abc1234def"), [])

    def test_sequence_flags_cannot_erase_a_competing_original_identity(self):
        binding = {
            "cpd": "Compound I-31",
            "binding_rule": "authoritative_structure_table_sequence",
            "authoritative_table_sequence_confirmed": True,
            "authoritative_table_label_count": 6,
            "authoritative_table_structure_count": 6,
            "visible_label_candidates": [{"label": "I-32", "source": "pdf_clip"}],
            "struct_area": 9000,
        }
        self.assertTrue(annotate_binding_accuracy(binding)["fail_closed"])

    def test_complete_identifiers_use_the_same_source_and_activity_key(self):
        for raw, expected in (
            ("10000", "10000"),
            ("I-44A", "I-44A"),
            ("44AB", "44AB"),
            ("A-001b", "A-001B"),
            ("0", "0"),
            ("1-2-3AB", "1-2-3AB"),
        ):
            with self.subTest(raw=raw):
                self.assertEqual(caption_identity(f"Compound {raw}")[0], expected)
                self.assertEqual(_normalize(raw, "id"), expected)
                self.assertEqual(_label(raw + "."), expected)
                self.assertEqual(normalize_compound(raw), f"Compound {expected}")

    def test_whitespace_cannot_merge_distinct_ids_or_suffix_tokens(self):
        for text in (
            "1 2",
            "1\n2",
            "44 A",
            "I-4 4",
            "8A 8B",
            "1/2",
            "123456789",
            "44ABCDE",
        ):
            with self.subTest(text=text):
                self.assertEqual(caption_identity("Compound " + text)[0], "")
                self.assertEqual(_normalize(text, "id"), "")
                self.assertEqual(_label(text), "")

    def test_native_numbered_grid_keeps_complete_prefixes_suffixes_and_original_cells(
        self,
    ):
        labels = ["10000", "I-44A", "44AB", "A-001b"]
        with fitz.open() as doc:
            page = doc.new_page()
            xs, ys = [40, 140, 390], [100, 130, 210, 290, 370, 450]
            for x in xs:
                page.draw_line((x, ys[0]), (x, ys[-1]))
            for y in ys:
                page.draw_line((xs[0], y), (xs[-1], y))
            page.insert_text((50, 120), "Compound No.", fontsize=9)
            page.insert_text((160, 120), "Structure", fontsize=9)
            structures = []
            for index, raw in enumerate(labels):
                y = ys[index + 1]
                page.insert_text((50, y + 30), raw, fontsize=9)
                structures.append(
                    {
                        "id": f"S{index}",
                        "idx": index,
                        "page_no": 1,
                        "x0": 165,
                        "x1": 300,
                        "y0": y + 10,
                        "y1": y + 70,
                        "image_path": "/controlled/source.png",
                    }
                )
            result = bind_numbered_tables(doc, structures, [0])
        self.assertEqual(
            [binding.label for binding in result.bindings],
            [raw.upper() for raw in labels],
        )
        self.assertFalse(result.issues)

    def test_native_visible_captions_are_not_limited_to_four_digits(self):
        for raw in ("10000", "I-44A", "44AB"):
            with self.subTest(raw=raw), fitz.open() as doc:
                page = doc.new_page()
                page.insert_text((90, 165), "Compound " + raw, fontsize=10)
                structures = [
                    {"id": "S", "page_no": 1, "x0": 60, "x1": 250, "y0": 80, "y1": 175}
                ]
                pairs = bind_visible_captions(doc, structures, {raw})
                self.assertEqual([binding.label for binding in pairs], [raw])

    def test_series_retains_original_prefix_and_never_corrects_duplicate_digits(self):
        numbers = [1, 2, 9, 4, 7, 8, 9, 10]
        result, payload = self.run_binding([f"I-{number}" for number in numbers])
        self.assertEqual(
            {binding["cpd"] for binding in result["bindings"]},
            {f"Compound I-{n}" for n in (1, 2, 4, 7, 8, 10)},
        )
        self.assertTrue(
            all(
                binding["cpd"]
                == "Compound " + binding["numbered_table_cell_evidence"]["source_label"]
                for binding in result["bindings"]
            )
        )
        self.assertTrue(payload["source_issues"])

    def test_case_and_wrapper_normalization_joins_only_the_same_literal_identity(self):
        rows = [
            {"cpd": "Example a-001b", "activity_values": {"IC50 (nM)": "7"}},
            {"cpd": "Compound A-01B", "activity_values": {"IC50 (nM)": "9"}},
        ]
        _, values = activity_order_and_map(rows)
        self.assertEqual(
            activity_for_compound(values, "Compound A-001B"), {"IC50 (nM)": "7"}
        )
        self.assertEqual(activity_for_compound(values, "Compound A-1B"), {})
