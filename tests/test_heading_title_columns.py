"""Original independent columns qualify title scope, never guessed neighbours."""

import copy
import unittest
from collections import Counter
from unittest.mock import patch

import fitz
from lateral_structure_support import LateralStructureControls

from patent_sar_extractor.core import title_ink_geometry
from patent_sar_extractor.core.heading_declaration_scope import declaration_candidates
from patent_sar_extractor.core.heading_original_replay import validate_original_heading
from patent_sar_extractor.core.heading_source_proof import heading_observation_status
from patent_sar_extractor.core.heading_title_columns import (
    title_column_windows,
    title_marks_outside_columns,
)
from patent_sar_extractor.core.heading_title_scope import replay_title_scope
from patent_sar_extractor.core.source_evidence_identity import proof_id
from patent_sar_extractor.core.source_geometry import source_layout


class HeadingTitleColumnTests(LateralStructureControls, unittest.TestCase):
    def test_binding_call_reuses_geometry_but_not_source_or_acceptance_results(self):
        counts = Counter()
        original = title_ink_geometry._title_ink_rows

        def calculate(source):
            counts[
                proof_id({"status": "original_title_geometry", "source": source})
            ] += 1
            return original(source)

        with patch.object(title_ink_geometry, "_title_ink_rows", side_effect=calculate):
            _result, payload = self.run_case(later_product=True, left_later_centre=430)
        self.assertEqual(len(payload["compound_catalog"]["entries"]), 6)
        self.assertTrue(counts)
        self.assertTrue(all(count == 1 for count in counts.values()), dict(counts))

    def original(self, *, ruled=True):
        _result, payload = self.run_case(
            later_product=True, left_later_centre=430, ruled=ruled
        )
        row = next(
            r
            for r in payload["compound_catalog"]["entries"]
            if r["cpd"] == "Compound B80"
        )
        evidence = row["original_heading_structure_evidence"]
        self.assertEqual(evidence["heading_source"]["title_scope"]["version"], 2)
        return payload, evidence

    def test_current_native_title_replays_full_physical_and_logical_column_sources(
        self,
    ):
        for ruled in (True, False):
            with self.subTest(ruled=ruled):
                _payload, evidence = self.original(ruled=ruled)
                with fitz.open(self.root / "original.pdf") as document:
                    validate_original_heading(document[0], evidence["heading_source"])

    def test_changed_original_row_paint_refuses_even_when_target_words_still_match(
        self,
    ):
        _payload, evidence = self.original()
        proof = copy.deepcopy(evidence["heading_source"])
        proof["title_scope"]["row_source"]["window"]["paints"].pop(0)
        with fitz.open(self.root / "original.pdf") as document:
            self.assertFalse(
                replay_title_scope(document[0], proof, source_layout(document[0]))
            )

    def test_foreign_page_document_and_duplicate_column_owners_refuse(self):
        _payload, evidence = self.original()
        original = evidence["heading_source"]
        for field, value in (
            ("original_pdf_sha256", "f" * 64),
            ("page_no", True),
            ("page_no", 2),
        ):
            proof = copy.deepcopy(original)
            proof["title_scope"][field] = value
            with self.subTest(field=field, value=value):
                self.assertEqual(heading_observation_status(proof)[0], "invalid")
        proof = copy.deepcopy(original)
        proof["title_scope"]["column_sources"].append(
            copy.deepcopy(proof["title_scope"]["column_sources"][0])
        )
        self.assertEqual(heading_observation_status(proof)[0], "invalid")

    def test_rehashed_title_cannot_remove_a_declaration_column_owner(self):
        _payload, evidence = self.original()
        heading, declaration = (
            copy.deepcopy(evidence["heading_source"]),
            copy.deepcopy(evidence["declaration_scope"]),
        )
        heading["title_scope"]["column_sources"].pop()
        declaration["heading_source_id"] = proof_id(heading)
        with self.assertRaisesRegex(ValueError, "column owners"):
            declaration_candidates(declaration, heading)

    def test_only_an_active_complete_row_has_column_ownership(self):
        _payload, evidence = self.original()
        scope = evidence["heading_source"]["title_scope"]
        windows = title_column_windows(
            scope["column_sources"],
            1,
            scope["page_size"],
            scope["original_pdf_sha256"],
            [360, 620, 480, 635],
            [0, 617, 660, 640],
        )
        self.assertEqual(windows, [])

    def test_an_already_complete_native_title_keeps_the_ordinary_fast_path(self):
        with patch(
            "patent_sar_extractor.core.heading_title_scope.title_column_windows",
            side_effect=AssertionError(
                "Complete native title must not expand its proof"
            ),
        ):
            _result, payload = self.run_case(
                ruled=False, later_product=True, left_later_centre=510
            )
        row = next(
            r
            for r in payload["compound_catalog"]["entries"]
            if r["cpd"] == "Compound B80"
        )
        self.assertEqual(
            row["original_heading_structure_evidence"]["heading_source"]["title_scope"][
                "version"
            ],
            1,
        )

    def test_cross_column_ink_and_competing_owners_are_not_silently_cropped(self):
        window, seek = [0, 100, 300, 125], [0, 100, 660, 125]
        marks = [[40, 65, 41, 600], [360, 105, 460, 119]]
        self.assertEqual(
            title_marks_outside_columns(marks, [window], seek), ([marks[1]], None)
        )
        for windows in ([window], [window, window]):
            marks = (
                [[290, 105, 360, 119]] if len(windows) == 1 else [[100, 105, 110, 119]]
            )
            with self.subTest(windows=windows):
                self.assertEqual(
                    title_marks_outside_columns(marks, windows, seek),
                    (None, "crossing_original_column_title_ink"),
                )


if __name__ == "__main__":
    unittest.main()
