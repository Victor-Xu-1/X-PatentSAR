from __future__ import annotations

import unittest

import fitz

from patent_sar_extractor.core.binding_spatial import collect_spatial_bindings
from patent_sar_extractor.core.visible_structure_binding import bind_visible_captions


def segment(name, *, page=1, x0=60, x1=220, y1=175):
    return {"id": name, "page_no": page, "x0": x0, "y0": 80, "x1": x1, "y1": y1}


class VisibleStructureBindingTests(unittest.TestCase):
    def test_elution_qualifier_preserves_printed_id_without_absolute_stereo_inference(
        self,
    ):
        from patent_sar_extractor.core.table_cells import prefixed_label

        self.assertEqual(prefixed_label("Compound 81 *first eluting isomer"), "81")
        self.assertEqual(prefixed_label("Compound 82 *second eluting isomer"), "82")
        self.assertEqual(prefixed_label("Compound 81 prepared from Compound 82"), "")

    def test_ruled_caption_above_structure_and_cross_page_caption_are_not_shifted(self):
        with fitz.open() as doc:
            structures = []
            xs = [60, 220, 380]
            for page_no, ys, labels, drawings in (
                (
                    1,
                    [100, 125, 205, 230],
                    [(0, ("1", "2")), (2, ("3", "4"))],
                    [(1, ("1", "2"))],
                ),
                (
                    2,
                    [100, 180, 205, 285],
                    [(1, ("5", "6"))],
                    [(0, ("3", "4")), (2, ("5", "6"))],
                ),
            ):
                page = doc.new_page()
                for x in xs:
                    page.draw_line((x, ys[0]), (x, ys[-1]))
                for y in ys:
                    page.draw_line((xs[0], y), (xs[-1], y))
                if page_no == 1:
                    page.insert_text((60, 85), "Table 21. Exemplary compounds")
                for row, ids in labels:
                    for col, label in enumerate(ids):
                        page.insert_text(
                            (xs[col] + 30, ys[row] + 16),
                            f"Compound {label}",
                            fontsize=9,
                        )
                for row, ids in drawings:
                    for col, label in enumerate(ids):
                        structures.append(
                            {
                                "id": "S" + label,
                                "page_no": page_no,
                                "x0": xs[col] + 45,
                                "x1": xs[col] + 100,
                                "y0": ys[row] + 20,
                                "y1": ys[row + 1] - 15,
                            }
                        )
            pairs = bind_visible_captions(doc, structures, None)
        self.assertEqual(
            {(b.label, b.structure["id"]) for b in pairs},
            {(str(n), "S" + str(n)) for n in range(1, 7)},
        )
        self.assertEqual(next(b for b in pairs if b.label == "3").label_page_no, 1)

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
            structures = [
                {**segment("one"), "idx": 0, "image_path": "one.png"},
                {**segment("two", page=2), "idx": 0, "image_path": "two.png"},
            ]
            observed = bind_visible_captions(doc, structures, {"8A"})
            self.assertEqual(len(observed), 2)  # Neither source observation is lost.
            result = collect_spatial_bindings(
                doc,
                structures,
                {0: doc[0].get_text(), 1: doc[1].get_text()},
                {},
                ["Compound 8A"],
                {},
                frozenset(),
            )
            self.assertEqual(result.candidates, ())
            self.assertEqual(result.reprints, ())
            self.assertEqual(
                {c.reason for c in result.conflicts}, {"ambiguous_compound_owner"}
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
