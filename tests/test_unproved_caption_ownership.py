"""Unknown literal titles stop ownership without removing original facts."""

import copy
import unittest

from patent_sar_extractor.core.caption_role_semantics import catalog_title_role
from patent_sar_extractor.core.formal_structure import coverage_errors
from patent_sar_extractor.core.source_body_context import original_context_extent
from patent_sar_extractor.core.source_geometry import SourceLayout, SourceTokens
from patent_sar_extractor.core.source_table_captions import table_caption_nominees
from patent_sar_extractor.core.structure_header_context import (
    observe_header_context,
    original_header_context_role,
)
from patent_sar_extractor.core.structure_header_lines import original_header_groups
from patent_sar_extractor.core.unruled_structure_proof import unruled_source_inventory
from tests.test_source_body_context import DIAGRAMS, WINDOW, context, token
from tests.unruled_structure_support import UnruledStructureControls


class UnprovedCaptionOwnershipTests(unittest.TestCase):
    def test_unknown_title_stops_trust_but_cannot_trim_the_original_inventory(self):
        for prefix in ("[0042", "［0042]", "[123456789]"):
            with self.subTest(prefix=prefix):
                text = prefix + " Table 9. Intermediate compounds"
                packets = context([token(text, 430, width=320)])
                before = copy.deepcopy(packets)
                extent = original_context_extent(packets, WINDOW, DIAGRAMS)
                self.assertEqual(extent["body_bottom"], WINDOW[3])
                self.assertEqual(extent["trusted_bottom"], 430)
                self.assertEqual(len(extent["unproved_boundaries"]), 1)
                self.assertEqual(packets, before)
                self.assertEqual(catalog_title_role(text), "unknown")

    def test_distinct_unknown_caption_is_retained_without_positive_role_or_id(self):
        words = [
            token("Table 8. Compounds", 430, x=20, width=160),
            token("[0042 Table 9. Intermediate compounds", 430, x=300, width=210),
        ]
        observed = table_caption_nominees(words, [520, 720])
        self.assertEqual(
            [row["text"] for row in observed], [word["text"] for word in words]
        )
        self.assertEqual(catalog_title_role(observed[1]["text"]), "unknown")

    def test_header_capture_starts_at_latest_unproved_title_not_an_old_role(self):
        words = [
            token("Table 8. Intermediate compounds", 200, width=300),
            token("[0042 Table 9. Compounds", 430, width=300),
        ]
        original = SourceTokens(
            words, SourceLayout((), (0, 0, 520, 720)), scan_bounds=(0, 0, 520, 720)
        )
        captured = observe_header_context(original, [520, 720], 500)
        texts = [packet["text"] for packet in captured]
        self.assertTrue(any("[0042 Table 9." in text for text in texts))
        self.assertFalse(any("Table 8." in text for text in texts))

    def test_title_cannot_be_wrapped_into_the_previous_physical_identifier_header(self):
        words = [
            token("Compound No.", 300, width=100),
            token("Structure", 300, x=240, width=100),
            token("[0042 Table 9.", 314, width=140),
        ]
        headers = original_header_groups(words, [0, 280, 520, 350])
        self.assertEqual(
            [[group["text"] for group in row] for row in headers],
            [["Compound No.", "Structure"]],
        )

    def test_saved_logical_header_projection_cannot_exclude_using_an_older_title(self):
        words = [
            token("Table 8. Intermediate compounds", 200, width=300),
            token("[0042 Table 9. Compounds", 430, width=300),
        ]
        original = SourceTokens(
            words, SourceLayout((), (0, 0, 520, 720)), scan_bounds=(0, 0, 520, 720)
        )
        logical = [0, 500, 520, 720]
        packets = observe_header_context(
            original, [520, 720], 500, logical_window=logical
        )
        before = copy.deepcopy(packets)
        self.assertEqual(
            original_header_context_role(packets, 500, 520, logical_window=logical),
            ("unknown", ""),
        )
        self.assertEqual(packets, before)


class UnprovedCaptionBindingTests(UnruledStructureControls, unittest.TestCase):
    def test_native_binder_retains_the_later_population_without_old_nonfinal_exclusion(
        self,
    ):
        def uncertain_table(page, _structures):
            page.insert_text((40, 315), "[0042 Table 22. Compounds", fontsize=10)

        result, payload = self.run_binding(
            ["73", "28", "901"],
            title="Table 12. Intermediates",
            mutate_page=uncertain_table,
        )
        issues, nonfinal = unruled_source_inventory(
            payload["source_sections"], payload["source_reference_scope"], []
        )
        self.assertEqual(nonfinal, {"S0", "S1"})
        self.assertNotIn("S2", nonfinal)
        self.assertTrue(
            any(
                issue["reason"] == "unproved_original_column_boundary"
                for issue in issues
            )
        )
        original = next(
            section["source"]
            for section in payload["source_sections"]
            if section["role"] == "unruled_structure_region"
        )
        self.assertEqual(
            {diagram["id"] for diagram in original["page_diagrams"]}, {"S0", "S1", "S2"}
        )
        self.assertEqual(result["compound_catalog"]["entries"], [])
        self.assertTrue(coverage_errors(payload))


if __name__ == "__main__":
    unittest.main()
