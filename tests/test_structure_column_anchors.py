"""One original column role survives changes in printed table rules."""

import unittest

from test_unruled_continuation import continued_page
from unruled_structure_support import UnruledStructureControls

from patent_sar_extractor.core.formal_structure import coverage_errors


def ruled_first_then_unruled(page, structures):
    for x in (40, 175, 380):
        page.draw_line((x, 65), (x, 330))
    for y in (65, 100, 210, 330):
        page.draw_line((40, y), (380, y))
    continued_page(page, structures)


def ruled_first_then_ruled(page, structures, *, disjoint=False):
    doc = page.parent
    for x in (40, 175, 380):
        page.draw_line((x, 65), (x, 330))
    for y in (65, 100, 210, 330):
        page.draw_line((40, y), (380, y))
    continued_page(page, structures, label_baseline_offset=-40 if disjoint else 4)
    next_page = doc[-1]
    rows = (65, 190, 320) if disjoint else (80, 200, 320)
    for x in (40, 175, 380):
        next_page.draw_line((x, rows[0]), (x, rows[-1]))
    for y in rows:
        next_page.draw_line((40, y), (380, y))


class StructureColumnAnchorTests(UnruledStructureControls, unittest.TestCase):
    def test_scanned_closed_rows_prove_disjoint_caption_and_drawing(self):
        result, payload = self.run_binding(
            ["73", "28"],
            raster=True,
            mutate_page=lambda page, structures: ruled_first_then_ruled(
                page, structures, disjoint=True
            ),
        )
        self.assertEqual(len(result["bindings"]), 4)
        self.assertEqual(coverage_errors(payload), [])

    def test_nonfinal_role_survives_a_headerless_physical_continuation(self):
        result, payload = self.run_binding(
            ["73", "28"],
            title="Table 12. Intermediate compounds",
            mutate_page=ruled_first_then_ruled,
        )
        self.assertEqual(result["bindings"], [])
        self.assertEqual(payload["source_issues"], [])

    def test_ruled_and_logical_parts_keep_one_nonrecursive_original_anchor(self):
        def chain(first, structures):
            doc = first.parent
            ruled_first_then_ruled(first, structures)
            continued_page(doc[0], structures, labels=("A17", "B80"))

        result, payload = self.run_binding(["73", "28"], mutate_page=chain)
        self.assertEqual(len(result["bindings"]), 6)
        self.assertEqual(coverage_errors(payload), [])

    def test_headerless_ruled_continuation_keeps_original_cell_row_ownership(self):
        result, payload = self.run_binding(
            ["73", "28"], mutate_page=ruled_first_then_ruled
        )
        self.assertEqual(len(result["bindings"]), 4)
        self.assertEqual(coverage_errors(payload), [])

    def test_original_physical_row_can_prove_disjoint_label_and_drawing_extents(self):
        result, payload = self.run_binding(
            ["73", "28"],
            mutate_page=lambda page, structures: ruled_first_then_ruled(
                page, structures, disjoint=True
            ),
        )
        self.assertEqual(len(result["bindings"]), 4)
        self.assertEqual(coverage_errors(payload), [])

    def test_actual_wrapped_grid_header_is_not_reconstructed_from_line_order(self):
        result, payload = self.run_binding(
            ["73", "28"],
            identifier_header="Compound\nNo.",
            mutate_page=ruled_first_then_unruled,
        )
        self.assertEqual(len(result["bindings"]), 4)
        self.assertEqual(coverage_errors(payload), [])

    def test_intervening_metadata_column_does_not_become_an_identifier_or_structure(
        self,
    ):
        def with_metadata(page, structures):
            page.insert_text((157, 80), "m/z", fontsize=8)
            page.insert_text((157, 154), "316", fontsize=8)
            page.insert_text((157, 269), "248", fontsize=8)
            for x in (40, 150, 200, 380):
                page.draw_line((x, 65), (x, 330))
            for y in (65, 100, 210, 330):
                page.draw_line((40, y), (380, y))
            continued_page(page, structures)

        result, payload = self.run_binding(["73", "28"], mutate_page=with_metadata)
        self.assertEqual(
            {b["cpd"] for b in result["bindings"]},
            {"Compound 73", "Compound 28", "Compound 901A", "Compound I-003B"},
        )
        self.assertEqual(coverage_errors(payload), [])

    def test_known_native_grid_header_disagreement_is_preserved(self):
        def conflicting_header(page):
            if page.number == 0:
                page.insert_text((50, 80), "Intermediate", fontsize=10, render_mode=3)

        result, payload = self.run_binding(
            ["73", "28"],
            raster=True,
            mutate_page=ruled_first_then_unruled,
            native_overlay=conflicting_header,
        )
        self.assertEqual(result["bindings"], [])
        self.assertTrue(coverage_errors(payload))

    def test_an_independent_final_product_survives_after_nonfinal_continuation(self):
        def following(first, structures):
            doc = first.parent
            ruled_first_then_unruled(first, structures)
            page = doc[-1]
            page.insert_text((40, 430), "Compound 800: Preparation", fontsize=10)
            page.draw_polyline(
                [
                    (235, 480),
                    (270, 460),
                    (310, 480),
                    (310, 520),
                    (270, 540),
                    (235, 520),
                    (235, 480),
                ]
            )
            structures.append(
                {
                    "structure_id": "FINAL",
                    "structure_index": len(structures),
                    "page_no": 2,
                    "bbox_pdf": [215, 450, 355, 550],
                }
            )

        result, payload = self.run_binding(
            ["73", "28"],
            title="Table 12. Intermediate compounds",
            mutate_page=following,
        )
        self.assertEqual(
            {b["cpd"]: b["structure_id"] for b in result["bindings"]},
            {"Compound 800": "FINAL"},
        )
        self.assertEqual(coverage_errors(payload), [])

    def test_ruled_first_page_and_unruled_continuation_keep_all_original_rows(self):
        result, payload = self.run_binding(
            ["73", "28"], mutate_page=ruled_first_then_unruled
        )
        self.assertEqual(
            {b["cpd"]: b["structure_id"] for b in result["bindings"]},
            {
                "Compound 73": "S0",
                "Compound 28": "S1",
                "Compound 901A": "C1-0",
                "Compound I-003B": "C1-1",
            },
        )
        self.assertEqual(coverage_errors(payload), [])

    def test_scanned_rule_changes_use_the_same_original_column_roles(self):
        result, payload = self.run_binding(
            ["73", "28"],
            raster=True,
            mutate_page=ruled_first_then_unruled,
            reverse=True,
        )
        self.assertEqual(len(result["bindings"]), 4)
        self.assertEqual(coverage_errors(payload), [])

    def test_explicit_nonfinal_role_does_not_become_final_when_table_rules_change(self):
        result, payload = self.run_binding(
            ["73", "28"],
            title="Table 12. Intermediate compounds",
            mutate_page=ruled_first_then_unruled,
        )
        self.assertEqual(result["bindings"], [])
        self.assertTrue(payload["source_sections"])
