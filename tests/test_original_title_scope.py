"""Native location boxes cannot crop away the original physical title ink."""

import copy
import hashlib
import json
import unittest
from unittest.mock import patch

import fitz

from patent_sar_extractor.core.binding_source_headings import observed_heading_blocks
from patent_sar_extractor.core.heading_evidence import original_heading_lines
from patent_sar_extractor.core.heading_observation import observe_heading
from patent_sar_extractor.core.heading_original_replay import validate_original_heading
from patent_sar_extractor.core.heading_source_proof import proved_heading_declaration
from tests.test_native_heading_coverage import original_cell


def native_nomination(page, literal="Compound 11"):
    return next(
        line for line in original_heading_lines(page) if line["text"] == literal
    )


class OriginalTitleScopeTests(unittest.TestCase):
    def setUp(self):
        self.factory = self.enterContext(
            patch(
                "patent_sar_extractor.core.page_ocr_cache._build_ocr_engine",
                side_effect=AssertionError(
                    "Generated scope checks use no native model"
                ),
            )
        )
        self.enterContext(
            patch(
                "patent_sar_extractor.core.text_ocr.source_capture.get_auxiliary_text_runtime",
                return_value=None,
            )
        )

    def tearDown(self):
        self.assertEqual(self.factory.call_count, 0)

    def reader(self, literal):
        def controlled(image, *, use_det, use_cls):
            return ([], None) if use_det else ([[literal, 0.99]], None)

        return controlled

    def observe(self, page, literal, *, nomination=None):
        nomination = nomination or native_nomination(page)
        digest = hashlib.sha256(page.parent.tobytes(no_new_id=True)).hexdigest()
        with patch(
            "patent_sar_extractor.core.heading_observation.get_ocr_engine",
            return_value=("rapidocr", self.reader(literal)),
        ):
            return observe_heading(page, nomination, digest)

    def test_native_only_locator_reads_the_outlined_nonfinal_prefix(self):
        for prefix in ("Intermediate", "Preparation of intermediate"):
            with (
                self.subTest(prefix=prefix),
                original_cell(prefix=prefix, outlined=True) as (_, page, _),
            ):
                hint = native_nomination(page)
                proof = json.loads(
                    json.dumps(self.observe(page, prefix + " Compound 11"))
                )
                declaration = proved_heading_declaration(proof)
                self.assertIsNotNone(declaration)
                self.assertEqual(declaration["role"], "intermediate_section")
                self.assertLess(proof["bbox"][0], hint["bbox"][0])
                self.assertEqual(proof["nomination"]["bbox"], hint["bbox"])
                self.assertEqual(proof["native_source"]["text"], "Compound 11")
                validate_original_heading(page, proof)

    def test_normal_inventory_does_not_publish_the_numbered_intermediate(self):
        with original_cell(prefix="Intermediate", outlined=True) as (doc, page, _):
            sections = []
            with patch(
                "patent_sar_extractor.core.heading_observation.get_ocr_engine",
                return_value=("rapidocr", self.reader("Intermediate Compound 11")),
            ):
                blocks = observed_heading_blocks(
                    doc, [0], {}, source_sections=sections, source_regions={0: []}
                )
            self.assertEqual(blocks, [])
            self.assertEqual([s["role"] for s in sections], ["intermediate_section"])
            validate_original_heading(page, sections[0]["heading_observation"])

    def test_an_independent_neighboring_column_is_not_swallowed_by_the_scope(self):
        with original_cell(prefix="Intermediate", outlined=True) as (doc, page, _):
            page.insert_text((350, 65), "Compound 88", fontsize=11)
            sections = []
            with patch(
                "patent_sar_extractor.core.heading_observation.get_ocr_engine",
                return_value=("rapidocr", self.reader("Intermediate Compound 11")),
            ):
                blocks = observed_heading_blocks(
                    doc, [0], {}, source_sections=sections, source_regions={0: []}
                )
            self.assertEqual([b["cpd"] for b in blocks], ["Compound 88"])
            self.assertEqual(len(sections), 2)
            for section in sections:
                validate_original_heading(page, section["heading_observation"])

    def test_repeating_the_native_subset_cannot_erase_outside_prefix_ink(self):
        with original_cell(prefix="Intermediate", outlined=True) as (_, page, _):
            self.assertIsNone(
                proved_heading_declaration(self.observe(page, "Compound 11"))
            )

    def test_wide_whitespace_does_not_discard_an_unrecognized_role_prefix(self):
        with original_cell(prefix="Intermediate" + " " * 20, outlined=True) as (
            _,
            page,
            _,
        ):
            proof = self.observe(page, "Intermediate Compound 11")
            declaration = proved_heading_declaration(proof)
            self.assertIsNotNone(declaration)
            self.assertEqual(declaration["role"], "intermediate_section")
            validate_original_heading(page, proof)

    def test_orphan_role_ink_with_multiple_native_owners_is_not_assigned_by_distance(
        self,
    ):
        with original_cell(prefix="Intermediate" + " " * 20, outlined=True) as (
            doc,
            page,
            _,
        ):
            page.insert_text((350, 65), "Compound 88", fontsize=11)
            sections = []
            with patch(
                "patent_sar_extractor.core.heading_observation.get_ocr_engine",
                side_effect=AssertionError(
                    "Ambiguous source ownership cannot load OCR"
                ),
            ):
                blocks = observed_heading_blocks(
                    doc, [0], {}, source_sections=sections, source_regions={0: []}
                )
            self.assertEqual({b["cpd"] for b in blocks}, {"Compound 11", "Compound 88"})
            self.assertTrue(all(s["status"] == "unresolved" for s in sections))

    def test_complete_native_source_keeps_the_fast_path_without_extra_ocr(self):
        with (
            original_cell() as (_, page, _),
            patch(
                "patent_sar_extractor.core.heading_observation.get_ocr_engine",
                side_effect=AssertionError("Complete native source needs no model"),
            ),
        ):
            digest = hashlib.sha256(page.parent.tobytes(no_new_id=True)).hexdigest()
            proof = observe_heading(page, native_nomination(page), digest)
            self.assertIsNotNone(proved_heading_declaration(proof))
            self.assertEqual(proof["observations"], [])
            self.assertIn("title_scope", proof)
            validate_original_heading(page, proof)

    def test_closed_original_cell_supplies_the_whole_title_not_the_native_subset(self):
        with original_cell(prefix="Intermediate", outlined=True) as (_, page, _):
            page.draw_rect(fitz.Rect(30, 40, 280, 90), width=0.4)
            proof = self.observe(page, "Intermediate Compound 11")
            declaration = proved_heading_declaration(proof)
            self.assertIsNotNone(declaration)
            self.assertEqual(declaration["role"], "intermediate_section")
            self.assertEqual(proof["title_scope"]["method"], "closed_cell")
            validate_original_heading(page, proof)

    def test_actual_prefix_changes_outside_the_old_box_invalidate_replay(self):
        with original_cell(prefix="Intermediate", outlined=True) as (_, page, _):
            proof = self.observe(page, "Intermediate Compound 11")
            self.assertIsNotNone(proved_heading_declaration(proof))
            page.draw_rect(fitz.Rect(41, 55, 43, 57), fill=(0, 0, 0))
            with self.assertRaises(ValueError):
                validate_original_heading(page, proof)

    def test_closed_number_box_cannot_exempt_adjacent_outside_role_ink(self):
        with original_cell(prefix="Intermediate", outlined=True) as (_, page, _):
            page.draw_rect(fitz.Rect(101, 45, 180, 79), width=0.4)
            with patch(
                "patent_sar_extractor.core.heading_observation.get_ocr_engine",
                side_effect=AssertionError(
                    "An incomplete physical title is not an OCR vote"
                ),
            ):
                digest = hashlib.sha256(page.parent.tobytes(no_new_id=True)).hexdigest()
                proof = observe_heading(page, native_nomination(page), digest)
            self.assertIsNone(proved_heading_declaration(proof))
            self.assertEqual(proof["observations"], [])

    def test_dotted_complete_native_cell_keeps_pixel_boundary_proof_and_no_ocr(self):
        with original_cell() as (_, page, _):
            page.draw_rect(fitz.Rect(30, 40, 280, 90), width=0.4, dashes="[1 1] 0")
            with patch(
                "patent_sar_extractor.core.heading_observation.get_ocr_engine",
                side_effect=AssertionError("A proved dotted native cell needs no OCR"),
            ):
                digest = hashlib.sha256(page.parent.tobytes(no_new_id=True)).hexdigest()
                proof = observe_heading(page, native_nomination(page), digest)
            self.assertIsNotNone(proved_heading_declaration(proof))
            self.assertEqual(proof["observations"], [])
            validate_original_heading(page, proof)

    def test_gapped_native_frame_is_not_an_observed_closed_title(self):
        with original_cell() as (_, page, _):
            page.draw_rect(fitz.Rect(30, 40, 280, 90), width=0.4, dashes="[1 3] 0")
            with patch(
                "patent_sar_extractor.core.heading_observation.get_ocr_engine",
                side_effect=AssertionError(
                    "Missing original edges cannot load a model"
                ),
            ):
                digest = hashlib.sha256(page.parent.tobytes(no_new_id=True)).hexdigest()
                proof = observe_heading(page, native_nomination(page), digest)
            self.assertIsNone(proved_heading_declaration(proof))

    def test_saved_scope_cannot_be_removed_or_cropped_back_to_native_words(self):
        with original_cell(prefix="Intermediate", outlined=True) as (_, page, _):
            proof = self.observe(page, "Intermediate Compound 11")
            self.assertIsNotNone(proved_heading_declaration(proof))
            removed = copy.deepcopy(proof)
            del removed["title_scope"]
            changed = copy.deepcopy(proof)
            changed["bbox"] = list(changed["nomination"]["bbox"])
            for forged in (removed, changed):
                forged["status"] = "confirmed"
                self.assertIsNone(proved_heading_declaration(forged))

    def test_crossing_graphic_ink_is_unresolved_before_model_loading(self):
        with original_cell() as (_, page, _):
            page.draw_rect(fitz.Rect(10, 10, 35, 115), width=0.5)
            with patch(
                "patent_sar_extractor.core.heading_observation.get_ocr_engine",
                side_effect=AssertionError(
                    "Unproved title geometry cannot load a model"
                ),
            ):
                digest = hashlib.sha256(page.parent.tobytes(no_new_id=True)).hexdigest()
                proof = observe_heading(page, native_nomination(page), digest)
            self.assertIsNone(proved_heading_declaration(proof))
            self.assertEqual(proof["observations"], [])

    def test_source_work_limits_refuse_whole_title_before_loading_models(self):
        with original_cell(prefix="Intermediate", outlined=True) as (_, page, _):
            with (
                patch(
                    "patent_sar_extractor.core.native_window_coverage.MAX_WINDOW_PAINTS",
                    2,
                ),
                patch(
                    "patent_sar_extractor.core.heading_observation.get_ocr_engine",
                    side_effect=AssertionError("Source overflow must not start OCR"),
                ),
            ):
                digest = hashlib.sha256(page.parent.tobytes(no_new_id=True)).hexdigest()
                proof = observe_heading(page, native_nomination(page), digest)
            self.assertIsNone(proved_heading_declaration(proof))
            self.assertEqual(proof["observations"], [])

    def test_malformed_scope_and_closed_pixel_omission_are_not_confirmation(self):
        with original_cell() as (_, page, _):
            page.draw_rect(fitz.Rect(30, 40, 280, 90), width=0.4)
            proof = self.observe(page, "Compound 11")
            self.assertIsNotNone(proved_heading_declaration(proof))
            mutations = []
            for field, value in (
                ("version", True),
                ("row_source", None),
                ("native_seed", {}),
                ("method", "trusted"),
            ):
                changed = copy.deepcopy(proof)
                changed["title_scope"][field] = value
                mutations.append(changed)
            changed = copy.deepcopy(proof)
            changed["title_scope"]["cell_source"]["pixels"] = None
            mutations.append(changed)
            for changed in mutations:
                changed["status"] = "confirmed"
                self.assertIsNone(proved_heading_declaration(changed))

    def test_native_dotted_activity_cells_share_actual_boundary_acceptance(self):
        from patent_sar_extractor.core.activity_grid_cells import read_activity_cell
        from patent_sar_extractor.core.native_cell_replay import (
            original_native_cell_matches,
        )
        from tests.test_native_heading_coverage import source_tokens

        for dashes, qualified in (("[1 1] 0", True), ("[1 3] 0", False)):
            with (
                self.subTest(dashes=dashes),
                original_cell(value="0.4") as (_, page, _),
            ):
                bounds = [30, 40, 150, 85]
                page.draw_rect(fitz.Rect(bounds), width=0.4, dashes=dashes)
                value, readings, review = read_activity_cell(
                    page, source_tokens(page), bounds, identifier=False, native=True
                )
                self.assertEqual(review, not qualified)
                self.assertEqual(
                    original_native_cell_matches(page, readings[0]), qualified
                )
                if qualified:
                    self.assertEqual(value, "0.4")

    def test_malformed_rule_geometry_in_saved_row_is_rejected_without_crashing(self):
        with original_cell() as (_, page, _):
            page.draw_rect(fitz.Rect(30, 40, 280, 90), width=0.4)
            proof = self.observe(page, "Compound 11")
            for field, value in (
                ("width", "not-a-number"),
                ("segments", [[None, 1, 2, 3]]),
                ("segments", [[float("nan"), 1, 2, 3]]),
            ):
                changed = copy.deepcopy(proof)
                paint = next(
                    p
                    for p in changed["title_scope"]["row_source"]["window"]["paints"]
                    if p["rule_path"] is not None
                )
                paint["rule_path"][field] = value
                with self.subTest(field=field, value=repr(value)):
                    self.assertIsNone(proved_heading_declaration(changed))

    def test_invisible_or_crossed_native_claims_stop_before_ocr(self):
        for mode in ("hidden", "crossed"):
            with self.subTest(mode=mode), original_cell() as (_, page, _):
                nomination = native_nomination(page)
                if mode == "hidden":
                    page.insert_text(
                        (40, 65), "Compound 12", fontsize=11, render_mode=3
                    )
                else:
                    page.draw_line((45, 60), (95, 60), width=2)
                with patch(
                    "patent_sar_extractor.core.heading_observation.get_ocr_engine",
                    side_effect=AssertionError(
                        "Unrecoverable native claims cannot load OCR"
                    ),
                ):
                    digest = hashlib.sha256(
                        page.parent.tobytes(no_new_id=True)
                    ).hexdigest()
                    proof = observe_heading(page, nomination, digest)
                self.assertIsNone(proved_heading_declaration(proof))
                self.assertEqual(proof["observations"], [])


if __name__ == "__main__":
    unittest.main()
