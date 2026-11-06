"""A diagram annotation and a real subsequent section have different owners."""

import copy
import unittest
from unittest.mock import patch

from native_reaction_support import NativeReactionFixture

from patent_sar_extractor.core.heading_original_replay import (
    original_heading_source_errors,
)
from patent_sar_extractor.core.heading_reaction_caption import _observe_label_source
from patent_sar_extractor.core.pipeline_rules import annotate_binding_accuracy
from patent_sar_extractor.core.source_evidence_identity import proof_id
from patent_sar_extractor.core.title_original_replay import replay_source_title
from tests.test_heading_physical_rows import controlled_reader, raster_heading


class ReactionCaptionBoundaryTests(NativeReactionFixture, unittest.TestCase):
    def test_scanned_caption_requires_matching_original_paired_reads(self):
        literal = "Intermediate A"
        with raster_heading(literal) as (_, page, nomination):
            line = {**nomination, "source": "page_ocr"}
            with (
                patch(
                    "patent_sar_extractor.core.page_ocr_cache.get_ocr_engine",
                    return_value=("rapidocr", controlled_reader(literal)),
                ),
                patch(
                    "patent_sar_extractor.core.text_ocr.source_capture.get_auxiliary_text_runtime",
                    return_value=None,
                ),
            ):
                source = _observe_label_source(page, line)
            self.assertEqual(source["method"], "raster")
            self.assertEqual(len(source["title"]["observations"]), 2)
            replay_source_title(page, source["title"])
            page.draw_line((35, 90), (120, 90))
            with self.assertRaises(ValueError):
                replay_source_title(page, source["title"])

    def test_scanned_caption_cannot_replace_the_original_identifier(self):
        with raster_heading("Intermediate A") as (_, page, nomination):
            line = {**nomination, "source": "page_ocr"}
            with (
                patch(
                    "patent_sar_extractor.core.page_ocr_cache.get_ocr_engine",
                    return_value=("rapidocr", controlled_reader("Intermediate B")),
                ),
                patch(
                    "patent_sar_extractor.core.text_ocr.source_capture.get_auxiliary_text_runtime",
                    return_value=None,
                ),
            ):
                self.assertIsNone(_observe_label_source(page, line))

    def test_a_bare_word_above_an_arrow_does_not_prove_caption_ownership(self):
        self.pair()
        self.arrow((180, 145), (250, 145))
        self.page.insert_text((190, 130), "Intermediate A", fontsize=9)
        self.assertEqual(self.select()[0], [])

    def test_a_real_later_intermediate_section_cannot_lend_its_route(self):
        self.page.insert_text((35, 80), "Intermediate A", fontsize=10)
        self.pair()
        self.arrow((180, 145), (250, 145))
        self.assertEqual(self.select()[0], [])

    def plus(self, x, y):
        self.page.draw_line((x - 6, y), (x + 6, y))
        self.page.draw_line((x, y - 6), (x, y + 6))

    def captioned_route(self):
        self.molecule("reagent", 40, 65)
        self.molecule("input", 230, 100)
        self.molecule("terminal", 490, 100)
        self.plus(190, 145)
        self.arrow((335, 145), (460, 145))
        self.page.insert_text((45, 167), "Intermediate A", fontsize=8)

    def test_proved_captioned_coreactant_does_not_cut_the_route(self):
        self.captioned_route()
        binding = self.assert_product("terminal")
        self.assertEqual(
            binding["original_heading_structure_evidence"]["candidate_count"], 3
        )

    def test_original_caption_and_route_are_replayed_after_binding(self):
        from patent_sar_extractor.core.title_geometry_memo import title_geometry_call

        self.captioned_route()
        binding = self.assert_product("terminal")

        @title_geometry_call
        def check_original():
            self.assertEqual(
                original_heading_source_errors(self.document, [binding]), []
            )
            self.page.insert_text((45, 167), "Intermediate B", fontsize=8)
            self.assertTrue(original_heading_source_errors(self.document, [binding]))

        check_original()

    def test_rehashed_terminal_owner_cannot_forge_an_input_caption(self):
        self.captioned_route()
        binding = copy.deepcopy(self.assert_product("terminal"))
        evidence = binding["original_heading_structure_evidence"]
        scope = evidence["declaration_scope"]
        scope["caption_witness"]["owner_id"] = "terminal"
        reaction = evidence["reaction_source"]
        reaction["declaration_scope_id"] = proof_id(scope)
        reaction["identity"] = proof_id(
            {k: v for k, v in reaction.items() if k != "identity"}
        )
        self.assertTrue(annotate_binding_accuracy(binding)["fail_closed"])
        self.assertTrue(original_heading_source_errors(self.document, [binding]))

    def test_route_memo_is_call_local_and_rejects_changed_graph_evidence(self):
        from patent_sar_extractor.core import heading_reaction
        from patent_sar_extractor.core.heading_declaration_scope import (
            declaration_candidates,
        )
        from patent_sar_extractor.core.title_geometry_memo import title_geometry_call

        self.captioned_route()
        evidence = self.assert_product("terminal")[
            "original_heading_structure_evidence"
        ]
        scope, heading = evidence["declaration_scope"], evidence["heading_source"]
        changed = copy.deepcopy(scope)
        changed["caption_witness"]["reaction"]["terminal_structure_id"] = "reagent"

        @title_geometry_call
        def compare():
            first = declaration_candidates(scope, heading)
            self.assertEqual(declaration_candidates(scope, heading), first)
            with self.assertRaises(ValueError):
                declaration_candidates(changed, heading)

        with patch(
            "patent_sar_extractor.core.heading_reaction.reaction_source_status",
            wraps=heading_reaction.reaction_source_status,
        ) as observed:
            compare()
        self.assertEqual(observed.call_count, 2)

    def test_saved_normal_source_plan_keeps_reaction_inputs_unassigned(self):
        from patent_sar_extractor.core.formal_structure import coverage_errors
        from patent_sar_extractor.core.ocsr.candidate_coverage import (
            candidate_coverage_errors,
        )
        from patent_sar_extractor.core.ocsr.recognition_inputs import recognition_inputs

        pdf, _, metadata, bindings, observations = self.saved_source(
            source_setup=self.captioned_route, terminal="terminal"
        )
        self.assertEqual(
            [r["cpd_id"] for r in observations["records"]], ["Compound 037B"]
        )
        self.assertEqual(len(observations["candidate_records"]), 2)
        self.assertTrue(all(not r["cpd_id"] for r in observations["candidate_records"]))
        self.assertEqual(coverage_errors(bindings), [])
        self.assertEqual(
            [item["structure_id"] for item in recognition_inputs(bindings).work_items],
            ["terminal"],
        )
        self.assertEqual(
            candidate_coverage_errors(
                self.root, {"input_pdf": str(pdf)}, metadata, bindings, observations
            ),
            [],
        )

    def test_captioned_coreactant_preserves_a_leftward_terminal(self):
        self.molecule("terminal", 40, 100)
        self.molecule("input", 230, 100)
        self.molecule("reagent", 450, 65)
        self.arrow((210, 145), (150, 145))
        self.plus(385, 145)
        self.page.insert_text((455, 167), "Intermediate B", fontsize=8)
        self.assert_product("terminal")

    def test_explicit_next_preparation_heading_cannot_be_skipped_by_a_route(self):
        self.molecule("reagent", 40, 65)
        self.molecule("input", 230, 100)
        self.molecule("terminal", 490, 100)
        self.plus(190, 145)
        self.arrow((335, 145), (460, 145))
        self.page.insert_text(
            (45, 167), "Intermediate A: Preparation of Intermediate A", fontsize=8
        )
        self.assertEqual(self.select()[0], [])

    def test_a_label_under_the_terminal_cannot_be_proved_as_an_input_caption(self):
        self.molecule("reagent", 40, 100)
        self.molecule("input", 230, 100)
        self.molecule("terminal", 490, 65)
        self.plus(190, 145)
        self.arrow((335, 145), (460, 145))
        self.page.insert_text((495, 167), "Intermediate A", fontsize=8)
        with patch(
            "patent_sar_extractor.core.heading_reaction_caption._observe_label_source",
            side_effect=AssertionError("Do not read a caption for a terminal diagram"),
        ):
            self.assertEqual(self.select()[0], [])

    def test_competing_captions_cannot_claim_one_reaction_input(self):
        self.molecule("reagent", 40, 65)
        self.molecule("input", 230, 100)
        self.molecule("terminal", 490, 100)
        self.plus(190, 145)
        self.arrow((335, 145), (460, 145))
        self.page.insert_text((45, 167), "Intermediate A", fontsize=8)
        self.page.insert_text((45, 179), "Intermediate B", fontsize=8)
        self.assertEqual(self.select()[0], [])

    def test_an_unconnected_route_is_not_promoted_by_a_reagent_annotation(self):
        self.pair()
        self.arrow((180, 145), (250, 145))
        self.molecule("S3", 80, 320)
        self.page.insert_text((190, 130), "Intermediate A", fontsize=9)
        self.assertEqual(self.select()[0], [])


if __name__ == "__main__":
    unittest.main()
