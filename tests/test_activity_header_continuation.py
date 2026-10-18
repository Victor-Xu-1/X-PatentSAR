"""Only geometry/context-proved header continuations share column identities."""

from __future__ import annotations

import unittest
from dataclasses import replace

from patent_sar_extractor.core.activity_grid_continuations import Panel, continued_panel
from patent_sar_extractor.core.activity_headers import context_from_text, grid_schema


class ActivityHeaderContinuationTests(unittest.TestCase):
    def continuation(self, first, second, old_axes, axes, prefix):
        prior = Panel(0, {"xs": old_axes, "ys": [100, 130, 150]}, first)
        region = {"xs": axes, "ys": [90, 110, 130]}
        return (
            continued_panel([prior], 1, region, second.context, prefix, second)
            or second
        )

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
        combined = self.continuation(
            first, second, axes, axes, "WO2026/123456 PCT/US2026/012345"
        )
        self.assertEqual(combined.groups, first.groups)
        self.assertEqual(combined.context, first.context)
        self.assertEqual(combined.raw_headers, second.raw_headers)

    def test_new_caption_units_or_geometry_do_not_borrow_context(self):
        first, second = self.schemas()
        axes = [20, 60, 160, 260]
        for prefix in ("Table 9. Different assay", "Different experiment conditions"):
            self.assertIs(self.continuation(first, second, axes, axes, prefix), second)
        _, different = self.schemas("uM")
        self.assertIs(self.continuation(first, different, axes, axes, ""), different)
        self.assertIs(
            self.continuation(first, second, axes, [20, 80, 160, 260], ""), second
        )

    def test_complete_repetition_never_overrides_original_review_or_column_roles(self):
        first, second = self.schemas()
        axes = [20, 60, 160, 260]
        group = second.groups[0]
        for current in (
            replace(second, needs_review=True),
            replace(second, header_resolution={"status": "unresolved"}),
            replace(second, raw_headers=()),
            replace(second, raw_headers=(*second.raw_headers[:2], "CellineYmin")),
            replace(
                second,
                groups=(
                    replace(group, value_columns=tuple(reversed(group.value_columns))),
                ),
            ),
            replace(
                second,
                groups=(
                    replace(
                        group,
                        value_columns=group.value_columns[:1],
                        metadata_columns=((2, "count"),),
                    ),
                ),
            ),
        ):
            with self.subTest(current=current):
                self.assertIs(
                    self.continuation(first, current, axes, axes, ""), current
                )
        unknown, _ = self.schemas()
        unknown = replace(unknown, groups=second.groups, raw_headers=second.raw_headers)
        self.assertIs(self.continuation(unknown, second, axes, axes, ""), second)


if __name__ == "__main__":
    unittest.main()
