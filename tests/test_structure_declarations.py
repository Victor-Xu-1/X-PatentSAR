"""Independent declared sources cannot disappear when no header was matched."""

import unittest

from test_unruled_continuation import continued_page
from unruled_structure_support import UnruledStructureControls

from patent_sar_extractor.core.formal_structure import coverage_errors


def independent_caption_page(
    first, structures, *, title="Table 13. Compounds", graph=True
):
    page = first.parent.new_page(width=520, height=720)
    page.insert_text((40, 45), title, fontsize=10)
    for n, label in enumerate(("901A", "I-003B")):
        top = 95 + n * 130
        if graph:
            page.draw_polyline(
                [
                    (230, top + 15),
                    (255, top),
                    (285, top + 15),
                    (285, top + 45),
                    (255, top + 60),
                    (230, top + 45),
                    (230, top + 15),
                ]
            )
            structures.append(
                {
                    "structure_id": f"CAP{n}",
                    "structure_index": len(structures),
                    "page_no": 2,
                    "bbox_pdf": [215, top, 355, top + 70],
                }
            )
        page.insert_text(
            (225 if graph else 60, top + 85),
            "Compound " + label if graph else label,
            fontsize=10,
        )


class StructureDeclarationTests(UnruledStructureControls, unittest.TestCase):
    def test_new_key_headerless_table_is_not_clean_partial_success(self):
        result, payload = self.run_binding(
            ["73", "28"],
            mutate_page=lambda page, structures: continued_page(
                page, structures, caption="Table 13. Continued"
            ),
        )
        self.assertEqual(len(result["compound_catalog"]["entries"]), 2)
        self.assertTrue(coverage_errors(payload))

    def test_scanned_new_key_source_keeps_the_same_completeness_requirement(self):
        result, payload = self.run_binding(
            ["73", "28"],
            raster=True,
            mutate_page=lambda page, structures: continued_page(
                page, structures, caption="Table 13. Continued"
            ),
        )
        self.assertEqual(len(result["compound_catalog"]["entries"]), 2)
        self.assertTrue(coverage_errors(payload))

    def test_independent_original_caption_proof_resolves_a_new_table_without_fake_columns(
        self,
    ):
        result, payload = self.run_binding(
            ["73", "28"], mutate_page=independent_caption_page
        )
        self.assertEqual(len(result["compound_catalog"]["entries"]), 4)
        self.assertEqual(coverage_errors(payload), [])

    def test_explicit_nonfinal_declaration_overrides_standalone_caption_default(self):
        result, payload = self.run_binding(
            ["73", "28"],
            mutate_page=lambda page, structures: independent_caption_page(
                page, structures, title="Table 13. Intermediate compounds"
            ),
        )
        self.assertEqual(
            {b["cpd"] for b in result["compound_catalog"]["entries"]},
            {"Compound 73", "Compound 28"},
        )
        self.assertEqual(coverage_errors(payload), [])

    def test_graph_free_declared_compound_source_is_not_omitted(self):
        _, payload = self.run_binding(
            ["73", "28"],
            mutate_page=lambda page, structures: independent_caption_page(
                page, structures, graph=False
            ),
        )
        self.assertTrue(coverage_errors(payload))

    def test_unknown_literal_table_key_still_preserves_an_explicit_nonfinal_role(self):
        result, payload = self.run_binding(
            ["73", "28"],
            mutate_page=lambda page, structures: independent_caption_page(
                page, structures, title="[0042] Table ABC. Intermediate compounds"
            ),
        )
        self.assertEqual(
            {b["cpd"] for b in result["compound_catalog"]["entries"]},
            {"Compound 73", "Compound 28"},
        )
        self.assertEqual(coverage_errors(payload), [])

    def test_an_unparsed_line_cannot_erase_a_graph_free_declared_source(self):
        def unread(first, structures):
            document = first.parent
            independent_caption_page(first, structures, graph=False)
            document[-1].insert_text((40, 690), "-7-", fontsize=9)

        _, payload = self.run_binding(["73", "28"], mutate_page=unread)
        self.assertTrue(coverage_errors(payload))

    def test_later_independent_preparation_is_not_excluded_with_the_table(self):
        def later(first, structures):
            document = first.parent
            independent_caption_page(
                first, structures, title="Table 13. Intermediate compounds"
            )
            page = document[-1]
            page.insert_text((40, 430), "Compound B80: Preparation", fontsize=10)
            page.draw_polyline(
                [
                    (230, 485),
                    (255, 470),
                    (285, 485),
                    (285, 515),
                    (255, 530),
                    (230, 515),
                    (230, 485),
                ]
            )
            structures.append(
                {
                    "structure_id": "LATER",
                    "structure_index": len(structures),
                    "page_no": 2,
                    "bbox_pdf": [215, 460, 355, 550],
                }
            )

        result, payload = self.run_binding(["73", "28"], mutate_page=later)
        self.assertEqual(
            {b["cpd"] for b in result["compound_catalog"]["entries"]},
            {"Compound 73", "Compound 28", "Compound B80"},
        )
        self.assertEqual(coverage_errors(payload), [])

    def test_graph_free_biology_table_does_not_claim_a_structure_inventory(self):
        def biology(first, _structures):
            page = first.parent.new_page(width=520, height=720)
            page.insert_text((40, 45), "Table 13. Biological results", fontsize=10)
            page.insert_text((50, 90), "Compound   IC50 (nM)", fontsize=10)
            page.insert_text((50, 130), "73         0.5", fontsize=10)

        result, payload = self.run_binding(["73", "28"], mutate_page=biology)
        self.assertEqual(len(result["compound_catalog"]["entries"]), 2)
        self.assertEqual(coverage_errors(payload), [])
