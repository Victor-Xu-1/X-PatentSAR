from __future__ import annotations

import unittest

import fitz

from patent_sar_extractor.core.visible_structure_binding import bind_visible_captions


def segment(name, *, page=1, x0=60, x1=220, y1=175):
    return {"id": name, "page_no": page, "x0": x0, "y0": 80, "x1": x1, "y1": y1}


class VisibleStructureBindingTests(unittest.TestCase):
    def test_native_prefixed_suffixes_have_separate_exact_owners(self):
        with fitz.open() as doc:
            page = doc.new_page()
            page.insert_text((90, 165), "Example 8A", fontsize=10)
            page.insert_text((300, 165), "Example 8B", fontsize=10)
            pairs = bind_visible_captions(
                doc,
                [segment("A"), segment("B", x0=270, x1=440)],
                {"8A", "8B"},
            )
            self.assertEqual(
                [(p.label, p.structure["id"]) for p in pairs],
                [("8A", "A"), ("8B", "B")],
            )
            self.assertTrue(
                all(p.observations[0]["method"] == "native_cell" for p in pairs)
            )

    def test_parent_caption_cannot_supply_a_letter_suffix(self):
        with fitz.open() as doc:
            doc.new_page().insert_text((90, 165), "Example 8", fontsize=10)
            self.assertEqual(
                bind_visible_captions(doc, [segment("parent")], {"8A", "8B"}), []
            )

    def test_prose_heading_above_a_diagram_is_not_a_caption(self):
        with fitz.open() as doc:
            doc.new_page().insert_text((90, 60), "Example 8A", fontsize=10)
            self.assertEqual(bind_visible_captions(doc, [segment("S")], {"8A"}), [])

    def test_ambiguous_overlapping_segments_are_not_bound(self):
        with fitz.open() as doc:
            doc.new_page().insert_text((90, 165), "Example 8A", fontsize=10)
            self.assertEqual(
                bind_visible_captions(doc, [segment("S"), segment("rival")], {"8A"}), []
            )

    def test_duplicate_caption_in_distinct_pages_remains_ambiguous(self):
        with fitz.open() as doc:
            for _ in range(2):
                doc.new_page().insert_text((90, 165), "Example 8A", fontsize=10)
            self.assertEqual(
                bind_visible_captions(
                    doc, [segment("one"), segment("two", page=2)], {"8A"}
                ),
                [],
            )

    def test_two_captions_cannot_own_the_same_segment(self):
        with fitz.open() as doc:
            page = doc.new_page()
            page.insert_text((75, 165), "Example 8A", fontsize=10)
            page.insert_text((150, 165), "Example 8B", fontsize=10)
            self.assertEqual(
                bind_visible_captions(doc, [segment("same")], {"8A", "8B"}), []
            )

    def test_unlocatable_rival_is_not_silently_ignored(self):
        with fitz.open() as doc:
            doc.new_page().insert_text((90, 165), "Example 8A", fontsize=10)
            for value in (None, float("nan"), -1, True):
                with self.subTest(value=value):
                    rival = {**segment("rival"), "x0": value}
                    self.assertEqual(
                        bind_visible_captions(doc, [segment("S"), rival], {"8A"}), []
                    )

    def test_duplicate_structure_identity_cannot_be_assigned_twice(self):
        with fitz.open() as doc:
            doc.new_page().insert_text((90, 165), "Example 8A", fontsize=10)
            doc.new_page().insert_text((90, 165), "Example 8B", fontsize=10)
            self.assertEqual(
                bind_visible_captions(
                    doc, [segment("same"), segment("same", page=2)], {"8A", "8B"}
                ),
                [],
            )


if __name__ == "__main__":
    unittest.main()
