"""Generated fully scanned originals through the normal binding facade."""

import unittest

import fitz
from lateral_structure_support import LateralStructureControls

from patent_sar_extractor.core.formal_structure import coverage_errors
from patent_sar_extractor.core.heading_original_replay import (
    original_heading_source_errors,
)


class RasterReactionFacadeTests(LateralStructureControls, unittest.TestCase):
    def test_unknown_ink_joining_one_frame_is_not_removed_or_borrowed_by_the_other(
        self,
    ):
        import test_heading_panel_scope as panels

        def crossing(page, records):
            page.draw_line((30, 180), (110, 180), width=1.5)

        _, payload = panels.HeadingPanelScopeTests.panel_source(
            self, variant="reaction", raster=True, mutate_panels=crossing
        )
        found = {
            row["cpd"]: row["structure_id"]
            for row in payload["compound_catalog"]["entries"]
        }
        self.assertNotIn("Compound I-017B", found)
        self.assertEqual(found.get("Compound 205"), "TERMINAL-205")
        self.assertTrue(coverage_errors(payload))

    def test_scanned_reaction_panels_retain_the_proved_original_border(self):
        import test_heading_panel_scope as panels

        _, payload = panels.HeadingPanelScopeTests.panel_source(
            self, variant="reaction", raster=True
        )
        found = {
            row["cpd"]: row["structure_id"]
            for row in payload["compound_catalog"]["entries"]
            if row["cpd"] in {"Compound I-017B", "Compound 205"}
        }
        self.assertEqual(
            found,
            {"Compound I-017B": "TERMINAL-I-017B", "Compound 205": "TERMINAL-205"},
            payload["source_issues"],
        )
        self.assertEqual(coverage_errors(payload), [])

    def test_scanned_original_heading_and_route_use_normal_text_and_binding_readers(
        self,
    ):
        for label, reverse in (("037B", True), ("I-017B", False)):
            with self.subTest(label=label, reverse=reverse):

                def original(document, records, *, label=label, reverse=reverse):
                    document.delete_page(0)
                    records.clear()
                    page = document.new_page(width=660, height=720)
                    page.insert_text(
                        (35, 40), f"Preparation of Compound {label}", fontsize=14
                    )
                    page.insert_text((35, 610), "Step 1: Preparation", fontsize=12)
                    self.add_drawing(page, records, -55, 150, "FIRST")
                    self.add_drawing(page, records, 205, 150, "SECOND")
                    tail, tip = (
                        ((280, 150), (210, 150))
                        if reverse
                        else ((210, 150), (280, 150))
                    )
                    sign = -1 if reverse else 1
                    page.draw_line(tail, tip)
                    page.draw_polyline(
                        [
                            (tip[0] - sign * 7, tip[1] - 4),
                            tip,
                            (tip[0] - sign * 7, tip[1] + 4),
                        ]
                    )

                _, payload = self.run_case(mutate_document=original, raster=True)
                entries = payload["compound_catalog"]["entries"]
                self.assertEqual(
                    [(row["cpd"], row["structure_id"]) for row in entries],
                    [("Compound " + label, "FIRST" if reverse else "SECOND")],
                    payload["source_issues"],
                )
                self.assertEqual(coverage_errors(payload), [])

                with fitz.open(self.root / "original.pdf") as document:
                    self.assertEqual(
                        original_heading_source_errors(document, entries), []
                    )
                self.assertEqual(payload["total_structures"], 2)


if __name__ == "__main__":
    unittest.main()
