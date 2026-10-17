"""Complete page observations nominate source gaps without repeated page OCR."""

import unittest
from unittest.mock import patch

import fitz

from patent_sar_extractor.core.binding_spatial import collect_spatial_bindings
from patent_sar_extractor.core.table_geometry import page_tokens
from patent_sar_extractor.core.unruled_structure_observation import (
    observe_unruled_tables,
)


class UnruledSourceAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.document = fitz.open()
        self.addCleanup(self.document.close)

    def page(self, text):
        page = self.document.new_page(width=520, height=720)
        page.insert_text((40, 80), text, fontsize=10)
        return page

    def test_unrelated_graph_free_prose_does_not_launch_coordinate_ocr(self):
        self.page("A synthetic procedure with no table declaration.")
        with patch("patent_sar_extractor.core.table_geometry.page_tokens") as reader:
            result = observe_unruled_tables(
                self.document,
                [],
                [0],
                lambda _p: [],
                reader,
                page_texts={0: "A synthetic procedure with no table declaration."},
            )
        reader.assert_not_called()
        self.assertEqual(result[1:3], ([], []))

    def test_invalid_page_candidates_cannot_select_another_original_page(self):
        self.page("Unrelated original source.")
        with patch("patent_sar_extractor.core.table_geometry.page_tokens") as reader:
            result = observe_unruled_tables(
                self.document,
                [],
                [-1, 1, True],
                lambda _p: [],
                reader,
            )
        reader.assert_not_called()
        self.assertEqual(result[1:3], ([], []))

    def test_known_diagram_page_cannot_be_suppressed_by_a_negative_text_hint(self):
        self.page("A synthetic procedure.")
        with patch(
            "patent_sar_extractor.core.table_geometry.page_tokens", wraps=page_tokens
        ) as reader:
            observe_unruled_tables(
                self.document,
                [{"page_no": 1}],
                [0],
                lambda _p: [],
                reader,
                page_texts={0: ""},
            )
        reader.assert_called_once()

    def test_missing_diagrams_do_not_hide_a_declared_original_structure_table(self):
        page = self.page("Table 9. Compounds")
        page.insert_text((50, 115), "Compound No.", fontsize=10)
        page.insert_text((240, 115), "Structure", fontsize=10)
        page.insert_text((60, 170), "18B", fontsize=10)
        page.insert_text((60, 240), "901", fontsize=10)
        result = collect_spatial_bindings(
            self.document,
            [],
            {0: page.get_text("text")},
            {},
            [],
            {},
            frozenset(),
            source_pages=[],
        )
        self.assertEqual(result.candidates, ())
        self.assertEqual(
            {
                c.label_key
                for c in result.conflicts
                if c.reason == "unbound_original_unruled_identifier"
            },
            {"18B", "901"},
        )
        self.assertEqual(len(result.source_sections), 1)


if __name__ == "__main__":
    unittest.main()
