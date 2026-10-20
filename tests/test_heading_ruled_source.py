"""Complete original heading text survives actual cell rules without guesses."""

import copy
import hashlib
import json
import unittest
from unittest.mock import patch

import fitz

from patent_sar_extractor.core.cell_ocr_observation import observe_cell
from patent_sar_extractor.core.heading_observation import observe_heading
from patent_sar_extractor.core.heading_source_proof import (
    heading_observation_status,
    proved_heading_declaration,
)
from patent_sar_extractor.core.source_section_roles import heading_members


def observe_original(
    label, *, ruled, missing_edge=None, dotted=False, shadow=None, retained_window=False
):
    with fitz.open() as original:
        page = original.new_page(width=360, height=240)
        page.insert_text((70, 90), label, fontsize=9.5)
        words = page.get_text("words")
        bounds = [
            min(w[0] for w in words),
            min(w[1] for w in words),
            max(w[2] for w in words),
            max(w[3] for w in words),
        ]
        if ruled:
            x0, y0, x1, y1 = 50, bounds[1] - 1, 240, bounds[3] + 1.5
            for name, start, end in (
                ("top", (x0, y0), (x1, y0)),
                ("bottom", (x0, y1), (x1, y1)),
                ("left", (x0, y0), (x0, y1)),
                ("right", (x1, y0), (x1, y1)),
            ):
                if name != missing_edge:
                    page.draw_line(
                        start, end, width=0.4, dashes="[1 1] 0" if dotted else None
                    )
        pixels = page.get_pixmap(matrix=fitz.Matrix(3, 3), alpha=False).tobytes("png")
    with fitz.open() as document:
        page = document.new_page(width=360, height=240)
        page.insert_image(page.rect, stream=pixels)
        page.insert_text(
            (40, 220), "Native footer only; controlled original", fontsize=8
        )
        if shadow:
            page.insert_text((70, 90), shadow, fontsize=9.5, render_mode=3)
        nomination = {
            "text": "Compound 999",  # A locator is deliberately not an authority.
            "bbox": bounds,
            "source": "page_ocr",
            "geometry_space": "rendered",
        }
        digest = hashlib.sha256(document.tobytes(no_new_id=True)).hexdigest()
        prior = (
            observe_heading(page, nomination, digest, grids=[])
            if retained_window
            else None
        )
        proof = observe_heading(page, nomination, digest)
        if prior is not None and proof["version"] == 2:
            proof["original_heading"] = prior
            proof["status"], _ = heading_observation_status(proof)
        return proof


class HeadingRuledSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cell = observe_original("Compound 82A", ruled=True, retained_window=True)
        if proved_heading_declaration(cls.cell) is None:
            raise AssertionError(
                "Positive closed-cell control must qualify before mutation checks"
            )

    def test_closed_original_cell_rules_do_not_erase_a_readable_printed_identifier(
        self,
    ):
        for label, identifier in (("Compound 71", "71"), ("Compound 82A", "82A")):
            with self.subTest(label=label):
                plain = observe_original(label, ruled=False)
                declaration = proved_heading_declaration(plain)
                self.assertIsNotNone(
                    declaration,
                    [(r["raw_text"], r["confidence"]) for r in plain["observations"]],
                )
                self.assertEqual(heading_members(declaration), [identifier])
                ruled = observe_original(label, ruled=True)
                saved = json.loads(json.dumps(ruled))
                declared = proved_heading_declaration(saved)
                self.assertIsNotNone(
                    declared,
                    [(r["raw_text"], r["confidence"]) for r in ruled["observations"]],
                )
                self.assertEqual(heading_members(declared), [identifier])

    def test_original_negative_words_are_not_dropped_with_cell_decoration(self):
        proof = observe_original("Not Compound 71", ruled=True)
        self.assertIsNone(proved_heading_declaration(json.loads(json.dumps(proof))))
        self.assertTrue(proof["observations"])
        self.assertEqual(proof["nomination"]["text"], "Compound 999")

    def test_physical_cell_is_selected_before_any_ocr_window_is_read(self):
        with patch(
            "patent_sar_extractor.core.heading_observation.observe_cell",
            wraps=observe_cell,
        ) as reader:
            proof = observe_original("Compound 71", ruled=True)
        self.assertIsNotNone(proved_heading_declaration(proof))
        self.assertEqual(
            reader.call_count, 2, "Read one complete cell at each existing resolution"
        )
        self.assertEqual(proof["original_heading"]["observations"], [])
        self.assertEqual([call.args[2] for call in reader.call_args_list], [400, 600])

    def test_saved_whole_cell_cannot_erase_an_independently_observed_negative_word(
        self,
    ):
        original = observe_original("Not Compound 71", ruled=True, retained_window=True)
        self.assertEqual(original["version"], 2)
        changed = copy.deepcopy(original)
        for reading in changed["observations"]:
            reading.update(text="Compound 71", raw_text="Compound 71", confidence=0.99)
            reading["parts"] = [
                {
                    "text": "Compound 71",
                    "confidence": 0.99,
                    "bbox": None,
                    "coordinate_space": "cell_ink_crop_pixels",
                }
            ]
            reading["detection_parts"] = []
            reading.pop("physical_header_lines", None)
        changed["status"] = "confirmed"
        self.assertIsNone(proved_heading_declaration(changed))

    def test_observed_dotted_rules_use_the_same_bounded_gap_policy(self):
        proof = observe_original("Compound 71", ruled=True, dotted=True)
        self.assertEqual(heading_members(proved_heading_declaration(proof)), ["71"])
        self.assertEqual(proof["version"], 2)

    def test_an_open_frame_cannot_be_completed_with_guessed_edges(self):
        for missing in ("left", "right"):
            with self.subTest(missing=missing):
                proof = observe_original(
                    "Compound 71", ruled=True, missing_edge=missing
                )
                self.assertIsNone(proved_heading_declaration(proof))
                self.assertEqual(proof["version"], 1)

    def test_native_shadow_conflict_remains_an_independent_veto(self):
        proof = observe_original("Compound 71", ruled=True, shadow="Compound 72")
        self.assertIsNone(proved_heading_declaration(proof))
        self.assertTrue(proof["native_source"]["text"])

    def test_saved_cell_cannot_drop_source_geometry_pixels_or_the_original_window(self):
        for field in ("grid_inventory", "cell", "pixels"):
            changed = copy.deepcopy(self.cell)
            del changed["cell_source"][field]
            with self.subTest(field=field):
                self.assertIsNone(proved_heading_declaration(changed))
        for field in ("original_heading", "cell_source"):
            changed = copy.deepcopy(self.cell)
            del changed[field]
            with self.subTest(field=field):
                self.assertIsNone(proved_heading_declaration(changed))
        changed = copy.deepcopy(self.cell)
        changed["original_heading"] = changed
        self.assertIsNone(proved_heading_declaration(changed))

    def test_saved_ambiguous_grid_or_shifted_nomination_cannot_choose_a_winner(self):
        cell = self.cell["bbox"]
        changed = copy.deepcopy(self.cell)
        changed["cell_source"]["grid_inventory"].append(
            {"xs": [cell[0] - 5, cell[2] + 5], "ys": [cell[1] - 2, cell[3] + 2]}
        )
        self.assertIsNone(proved_heading_declaration(changed))
        shifted = copy.deepcopy(self.cell)
        shifted["nomination"]["bbox"][0] = cell[0] - 1
        self.assertIsNone(proved_heading_declaration(shifted))

    def test_known_disjoint_weak_or_foreign_detector_claims_are_not_boundary_fragments(
        self,
    ):
        for mutation in ("disjoint", "weak_whole", "foreign_whole", "annotation"):
            changed = copy.deepcopy(self.cell)
            for reading in changed["original_heading"]["observations"]:
                parts = reading["detection_parts"]
                if mutation == "disjoint":
                    parts[0].update(
                        text="Compound 8",
                        confidence=0.99,
                        bbox=[[10.0, 20.0], [90.0, 20.0], [90.0, 50.0], [10.0, 50.0]],
                    )
                elif mutation == "weak_whole":
                    # Preserve the intended strong partial-ID claim even if
                    # the full-window renderer changes upstream tokenization.
                    parts[0].update(text="Compound 8", confidence=0.99)
                    parts[-1]["confidence"] = 0.3
                elif mutation == "foreign_whole":
                    parts[-1]["text"] = "83B"
                else:
                    parts[0]["text"] = "Compound 8 first eluting isomer"
            with self.subTest(mutation=mutation):
                self.assertIsNone(proved_heading_declaration(changed))


if __name__ == "__main__":
    unittest.main()
