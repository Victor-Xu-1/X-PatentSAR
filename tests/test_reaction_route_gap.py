"""A wrapped source cannot jump over unowned original ink.

Generated native documents only. These controls exercise source ownership and
complete route replay, not chemical feasibility or recognition accuracy.
"""

import unittest
from unittest.mock import patch

from native_reaction_support import NativeReactionFixture


class ReactionRouteGapTests(NativeReactionFixture, unittest.TestCase):
    def wrapped(self):
        self.molecule("start", 60, 100)
        self.molecule("middle", 290, 100)
        self.molecule("continued", 60, 320)
        self.molecule("target", 290, 320)
        self.arrow((175, 145), (260, 145))
        self.arrow((405, 145), (545, 145))
        self.arrow((175, 365), (260, 365))

    def test_unowned_native_text_cannot_disappear_between_wrapped_rows(self):
        self.wrapped()
        self.page.insert_text((35, 260), "Independent original material", fontsize=10)
        self.assertEqual(len(self.select()[0]), 0)

    def test_unowned_vector_ink_cannot_disappear_between_wrapped_rows(self):
        self.wrapped()
        self.page.draw_line((400, 250), (440, 250))
        self.assertEqual(len(self.select()[0]), 0)

    def test_observed_conditions_inside_a_complete_row_do_not_invent_a_gap(self):
        self.wrapped()
        self.page.insert_text((200, 118), "THF", fontsize=10)
        self.assert_product("target")

    def test_source_gap_budget_refuses_the_whole_route_without_sampling(self):
        self.wrapped()
        with patch("patent_sar_extractor.core.reaction_layout.MAX_LAYOUT_GAP_WORK", 1):
            self.assertEqual(len(self.select()[0]), 0)
        self.assert_product("target")


if __name__ == "__main__":
    unittest.main()
