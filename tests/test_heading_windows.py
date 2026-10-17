"""Physical multiline title controls, not concatenation of ID characters."""

import unittest

import fitz

from patent_sar_extractor.core.binding_source_headings import observed_heading_blocks
from patent_sar_extractor.core.binding_source_references import (
    reference_issues,
    reference_scope,
)


class HeadingWindowTests(unittest.TestCase):
    @staticmethod
    def document(lines, *, leading=18, font="helv", fontsize=11):
        document = fitz.open()
        page = document.new_page(width=600, height=600)
        for index, text in enumerate(lines):
            page.insert_text(
                (40, 65 + index * leading), text, fontsize=fontsize, fontname=font
            )
        return document

    def test_native_complete_ids_can_continue_on_the_next_original_row(self):
        for lines in (["Compounds 73 and", "74"], ["Compounds Z-007B,", "Z-007C"]):
            with self.subTest(lines=lines), self.document(lines) as document:
                sections = []
                blocks = observed_heading_blocks(
                    document, [0], {}, source_sections=sections
                )
            self.assertEqual(len(blocks), 2)
            self.assertEqual(len(sections), 1)
            self.assertEqual(
                len(sections[0]["heading_observation"]["nomination"]["rows"]), 2
            )
            self.assertEqual(sections[0]["status"], "confirmed")

    def test_wrapped_biology_title_does_not_declare_terminal_compounds(self):
        with self.document(["Examples 71 and 86", "Biological evaluation"]) as document:
            sections = []
            self.assertEqual(
                observed_heading_blocks(document, [0], {}, source_sections=sections), []
            )
        self.assertEqual(sections[0]["role"], "assay_section")
        payload = {
            "source_sections": sections,
            "source_reference_scope": reference_scope(sections),
        }
        self.assertEqual(reference_issues(payload, []), [])

    def test_unfinished_list_does_not_swallow_body_or_the_next_heading(self):
        with self.document(
            ["Compounds 73 and", "A solution was added.", "Compound 92: Synthesis"]
        ) as document:
            sections = []
            blocks = observed_heading_blocks(
                document, [0], {}, source_sections=sections
            )
        self.assertEqual([block["cpd"] for block in blocks], ["Compound 92"])
        self.assertEqual(sections[0]["role"], "unproved_heading")
        payload = {
            "source_sections": sections,
            "source_reference_scope": reference_scope(sections),
        }
        self.assertTrue(reference_issues(payload, [{"cpd": "Compound 92"}]))

    def test_range_and_split_id_characters_remain_unresolved_not_expanded(self):
        for lines in (
            ["Compounds 2 through 8"],
            ["Compounds G-00", "7A and 9B"],
            ["Example 7 and Example 9"],
        ):
            with self.subTest(lines=lines), self.document(lines) as document:
                sections = []
                self.assertEqual(
                    observed_heading_blocks(
                        document, [0], {}, source_sections=sections
                    ),
                    [],
                )
            self.assertEqual(
                sections[0]["status"],
                "unresolved",
                {
                    name: sections[0]["heading_observation"][name]
                    for name in (
                        "bbox",
                        "nomination",
                        "observations",
                        "rendered_frames",
                    )
                },
            )

    def test_ninth_physical_heading_row_fails_instead_of_truncating(self):
        lines = ["Compounds 1,"] + [f"{index}," for index in range(2, 9)] + ["9"]
        with (
            self.document(lines, leading=12, fontsize=9) as document,
            self.assertRaisesRegex(ValueError, "eight rows"),
        ):
            observed_heading_blocks(document, [0], {})

    def test_chinese_original_group_identifiers_are_preserved(self):
        with self.document(["化合物 73和74"], font="china-s") as document:
            blocks = observed_heading_blocks(document, [0], {})
        self.assertEqual(
            [block["cpd"] for block in blocks], ["Compound 73", "Compound 74"]
        )

    def test_real_scanned_multiline_window_uses_the_same_bounded_cell_reader(self):
        lines = ["Compounds 73 and", "74"]
        with self.document(lines) as original:
            hints = []
            groups = {}
            for word in original[0].get_text("words"):
                groups.setdefault(tuple(word[5:7]), []).append(word)
            rows = sorted(
                groups.values(), key=lambda words: min(word[1] for word in words)
            )
            self.assertEqual(len(rows), len(lines))
            for text, words in zip(lines, rows):
                self.assertTrue(words)
                bounds = [
                    min(w[0] for w in words),
                    min(w[1] for w in words),
                    max(w[2] for w in words),
                    max(w[3] for w in words),
                ]
                hints.append(
                    {
                        "text": text,
                        "y0": bounds[1],
                        "bbox": bounds,
                        "source": "page_ocr",
                        "geometry_space": "rendered",
                    }
                )
            pixels = (
                original[0]
                .get_pixmap(matrix=fitz.Matrix(3, 3), alpha=False)
                .tobytes("png")
            )
        with fitz.open() as document:
            page = document.new_page(width=600, height=600)
            page.insert_image(page.rect, stream=pixels)
            sections = []
            blocks = observed_heading_blocks(
                document, [0], {}, source_sections=sections, source_line_map={0: hints}
            )
        self.assertEqual(
            [block["cpd"] for block in blocks], ["Compound 73", "Compound 74"]
        )
        self.assertTrue(
            all(
                "physical_header_lines" in reading
                for reading in sections[0]["heading_observation"]["observations"]
            )
        )


if __name__ == "__main__":
    unittest.main()
