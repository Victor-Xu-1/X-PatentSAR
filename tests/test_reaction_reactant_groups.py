"""Explicit original addition symbols, not proximity, supply co-reactant roles."""

import copy
import unittest
from unittest.mock import patch

from native_reaction_consumers import assert_web_original, assert_worker_checkpoint
from native_reaction_support import NativeReactionFixture

from patent_sar_extractor.core.heading_original_replay import (
    original_heading_source_errors,
)
from patent_sar_extractor.core.heading_reaction import reaction_source_status
from patent_sar_extractor.core.source_evidence_identity import proof_id


class ReactionReactantGroupTests(NativeReactionFixture, unittest.TestCase):
    def plus(self, x, y, *, symbol="plus"):
        if symbol == "glyph":
            self.page.insert_text((x - 5, y + 4), "+", fontsize=16)
            return
        if symbol == "cross":
            self.page.draw_line((x - 6, y - 6), (x + 6, y + 6))
            self.page.draw_line((x - 6, y + 6), (x + 6, y - 6))
            return
        self.page.draw_line((x - 6, y), (x + 6, y))
        if symbol != "minus":
            self.page.draw_line((x, y - (0 if symbol == "tee" else 6)), (x, y + 6))
        if symbol == "asterisk":
            self.page.draw_line((x - 5, y - 5), (x + 5, y + 5))

    def two_inputs(self, *, symbol="plus"):
        self.molecule("first-input", 40, 100)
        self.molecule("adjacent-input", 230, 100)
        self.molecule("terminal", 490, 100)
        self.arrow((335, 145), (460, 145))
        self.plus(190, 145, symbol=symbol)

    def test_two_explicitly_added_reactants_have_one_terminal(self):
        self.two_inputs()
        binding = self.assert_product("terminal")
        reaction = binding["original_heading_structure_evidence"]["reaction_source"]
        self.assertEqual(reaction["version"], 4)
        groups = reaction["reactant_groups"]
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["page_no"], 1)
        self.assertEqual(
            set(groups[0]["steps"][0]["input_ids"]), {"first-input", "adjacent-input"}
        )
        self.assertEqual(original_heading_source_errors(self.document, [binding]), [])

    def test_leftward_reaction_does_not_make_the_last_drawing_the_product(self):
        self.molecule("terminal", 40, 100)
        self.molecule("near-input", 230, 100)
        self.molecule("far-input", 450, 100)
        self.arrow((210, 145), (150, 145))
        self.plus(385, 145)
        self.assert_product("terminal")

    def test_a_complete_three_input_chain_is_conserved(self):
        for name, x in (("one", 30), ("two", 180), ("three", 330), ("end", 530)):
            self.molecule(name, x, 100)
        self.arrow((445, 145), (500, 145))
        self.plus(145, 145)
        self.plus(295, 145)
        binding = self.assert_product("end")
        group = binding["original_heading_structure_evidence"]["reaction_source"][
            "reactant_groups"
        ][0]["steps"][0]
        self.assertEqual(set(group["input_ids"]), {"one", "two", "three"})
        self.assertEqual(len(group["connectors"]), 2)

    def test_previously_observed_products_can_be_co_inputs_of_a_later_step(self):
        for name, x, y in (
            ("upper-left", 40, 60),
            ("upper-right", 230, 60),
            ("left-input", 40, 280),
            ("right-input", 230, 280),
            ("terminal", 490, 280),
        ):
            self.molecule(name, x, y)
        self.arrow((82, 175), (82, 250))
        self.arrow((272, 175), (272, 250))
        self.arrow((335, 325), (460, 325))
        self.plus(190, 325)
        self.assert_product("terminal")

    def test_vertical_original_addition_preserves_upward_direction(self):
        self.molecule("terminal", 100, 70)
        self.molecule("near-input", 100, 280)
        self.molecule("far-input", 100, 450)
        self.arrow((142, 260), (142, 190))
        self.plus(142, 410)
        self.assert_product("terminal")

    def test_a_text_glyph_is_not_replaced_with_unobserved_vector_strokes(self):
        self.two_inputs(symbol="minus")
        self.page.insert_text((184, 149), "+", fontsize=16)
        self.assertEqual(self.select()[0], [])

    def test_a_literal_native_plus_uses_original_cell_and_paint_proof(self):
        self.two_inputs(symbol="glyph")
        binding = self.assert_product("terminal")
        proof = binding["original_heading_structure_evidence"]["reaction_source"]
        cells = proof["input_operators"][0]["cells"]
        self.assertEqual([cell["text"] for cell in cells], ["+"])
        self.assertEqual(original_heading_source_errors(self.document, [binding]), [])

    def test_a_covered_native_operator_cannot_create_a_reactant_role(self):
        self.two_inputs(symbol="glyph")
        import fitz

        self.page.draw_rect(fitz.Rect(180, 130, 205, 155), color=None, fill=(1, 1, 1))
        self.assertEqual(self.select()[0], [])

    def test_dropping_native_operator_carriers_cannot_keep_a_saved_input_group(self):
        self.two_inputs(symbol="glyph")
        source = self.assert_product("terminal")["original_heading_structure_evidence"]
        changed = copy.deepcopy(source["reaction_source"])
        changed["input_operators"][0]["cells"] = []
        changed.pop("identity")
        changed["identity"] = proof_id(changed)
        with self.assertRaises(ValueError):
            reaction_source_status(
                changed, source["declaration_scope"], source["heading_source"]
            )

    def test_original_glyph_readback_does_not_accept_changed_source_text(self):
        self.two_inputs(symbol="glyph")
        binding = self.assert_product("terminal")
        import fitz

        self.page.add_redact_annot(fitz.Rect(180, 125, 210, 155))
        self.page.apply_redactions()
        self.page.insert_text((185, 149), "X", fontsize=16)
        self.assertTrue(original_heading_source_errors(self.document, [binding]))

    def test_a_resource_limit_refuses_instead_of_sampling_input_groups(self):
        self.two_inputs()
        with patch("patent_sar_extractor.core.reaction_reactants.MAX_ADDITION_WORK", 1):
            self.assertEqual(self.select()[0], [])
        self.assert_product("terminal")

    def test_native_glyphs_and_strokes_share_one_addition_sign_budget(self):
        for name, x in (("one", 30), ("two", 180), ("three", 330), ("end", 530)):
            self.molecule(name, x, 100)
        self.arrow((445, 145), (500, 145))
        self.plus(145, 145)
        self.plus(295, 145, symbol="glyph")
        with patch(
            "patent_sar_extractor.core.reaction_reactants.MAX_ADDITION_SIGNS", 1
        ):
            self.assertEqual(self.select()[0], [])
        self.assert_product("end")

    def assert_symbol_refused(self, symbol):
        self.two_inputs(symbol=symbol)
        self.assertEqual(self.select()[0], [])

    def test_a_minus_cannot_supply_a_reactant_role(self):
        self.assert_symbol_refused("minus")

    def test_a_cross_cannot_supply_a_reactant_role(self):
        self.assert_symbol_refused("cross")

    def test_an_incomplete_tee_cannot_supply_a_reactant_role(self):
        self.assert_symbol_refused("tee")

    def test_extra_asterisk_ink_cannot_be_discarded(self):
        self.assert_symbol_refused("asterisk")

    def test_an_unattached_drawing_cannot_be_lost_behind_a_valid_input_group(self):
        self.two_inputs()
        self.molecule("unresolved", 230, 320)
        self.assertEqual(self.select()[0], [])

    def test_an_added_product_side_drawing_is_not_a_co_reactant(self):
        self.molecule("input", 40, 100)
        self.molecule("first-output", 300, 100)
        self.molecule("second-output", 530, 100)
        self.arrow((155, 145), (270, 145))
        self.plus(450, 145)
        self.assertEqual(self.select()[0], [])

    def test_source_ink_across_an_addition_connection_is_not_ignored(self):
        self.two_inputs()
        self.page.insert_text((150, 149), "N", fontsize=12)
        self.assertEqual(self.select()[0], [])

    def test_group_inventory_cannot_be_dropped_reordered_or_rehashed_into_legacy(self):
        self.two_inputs()
        binding = self.assert_product("terminal")
        source = binding["original_heading_structure_evidence"]
        original = source["reaction_source"]
        changes = []
        changed = copy.deepcopy(original)
        changed["reactant_groups"] = []
        changes.append(changed)
        changed = copy.deepcopy(original)
        changed["reactant_groups"][0]["steps"][0]["input_ids"].reverse()
        changes.append(changed)
        changed = copy.deepcopy(original)
        changed["version"], changed["status"] = 2, "observed_native_reaction"
        del changed["reactant_groups"]
        del changed["input_operators"]
        changes.append(changed)
        changed = copy.deepcopy(original)
        changed["reactant_groups"][0]["steps"][0]["step_index"] = False
        changes.append(changed)
        for changed in changes:
            changed.pop("identity")
            changed["identity"] = proof_id(changed)
            with (
                self.subTest(version=changed["version"]),
                self.assertRaises(ValueError),
            ):
                reaction_source_status(
                    changed, source["declaration_scope"], source["heading_source"]
                )

    def test_changed_actual_original_symbol_revokes_saved_ownership(self):
        self.two_inputs()
        binding = self.assert_product("terminal")
        self.page.draw_line((183, 138), (197, 152), width=2)
        self.assertTrue(original_heading_source_errors(self.document, [binding]))

    def test_normal_worker_and_checkpoint_replay_multi_input_source(self):
        assert_worker_checkpoint(
            self,
            source_setup=self.two_inputs,
            terminal="terminal",
            unassigned=("first-input", "adjacent-input"),
        )

    def test_web_and_final_qa_reject_rehashed_foreign_multi_input_ink(self):
        assert_web_original(
            self,
            source_setup=self.two_inputs,
            terminal="terminal",
        )


if __name__ == "__main__":
    unittest.main()
