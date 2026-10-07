"""Only geometry/context-proved header continuations share column identities."""

from __future__ import annotations

import unittest

from patent_sar_extractor.core.activity_grid_cells import continued_header_schema
from patent_sar_extractor.core.activity_headers import context_from_text, grid_schema


class ActivityHeaderContinuationTests(unittest.TestCase):
    def schemas(self, unit="nM"):
        first = grid_schema(
            context_from_text("Table 8. Original proliferation assay"),
            [
                ["Example #", "Unrelated target EC50 (nM)", "Cell line Ymin"],
                ["1", "0.1", "2"],
            ],
        )
        second = grid_schema(
            context_from_text("WO2026/123456\nPCT/US2026/012345"),
            [
                ["Example #", f"UnrelatedtargetEC50 ({unit})", "CelllineYmin"],
                ["2", "0.2", "3"],
            ],
        )
        return first, second

    def test_repeated_original_headers_share_keys_but_keep_current_raw_header(self):
        first, second = self.schemas()
        axes = [20, 60, 160, 260]
        combined = continued_header_schema(
            first, second, axes, axes, "WO2026/123456 PCT/US2026/012345"
        )
        self.assertEqual(combined.groups, first.groups)
        self.assertEqual(combined.context, first.context)
        self.assertEqual(combined.raw_headers, second.raw_headers)

    def test_new_caption_units_or_geometry_do_not_borrow_context(self):
        first, second = self.schemas()
        axes = [20, 60, 160, 260]
        for prefix in ("Table 9. Different assay", "Different experiment conditions"):
            self.assertIs(
                continued_header_schema(first, second, axes, axes, prefix), second
            )
        _, different = self.schemas("uM")
        self.assertIs(
            continued_header_schema(first, different, axes, axes, ""), different
        )
        self.assertIs(
            continued_header_schema(first, second, axes, [20, 80, 160, 260], ""), second
        )


if __name__ == "__main__":
    unittest.main()
