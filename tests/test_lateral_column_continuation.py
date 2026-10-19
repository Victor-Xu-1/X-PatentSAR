"""Parallel continuations conserve original column-local parents and gaps."""

import json
import unittest

from lateral_structure_support import LateralStructureControls

from patent_sar_extractor.core.binding_source_references import (
    reference_issues,
    reference_scope,
)
from patent_sar_extractor.core.formal_structure import coverage_errors
from patent_sar_extractor.core.source_evidence_identity import proof_id
from patent_sar_extractor.core.unruled_continuation_titles import qualified_table_key
from patent_sar_extractor.web.compound_catalog import read_compound_catalog


class LateralColumnContinuationTests(LateralStructureControls, unittest.TestCase):
    def continued_tables(
        self,
        document,
        records,
        *,
        same_page=False,
        right_prefix="",
        prior_right_experiment=False,
        captioned=False,
    ):
        if prior_right_experiment:
            document[0].insert_text(
                (360, 430), "Compound B80: Preparation", fontsize=10
            )
            self.add_drawing(document[0], records, 360, 510, "INDEPENDENT-B80")
        page = document[0] if same_page else document.new_page(width=660, height=720)
        ys, centres = (
            ([460, 575, 690], [510, 625]) if same_page else ([80, 210, 330], [150, 265])
        )
        for column, left in enumerate((40, 360)):
            if column and right_prefix:
                page.insert_text((left, ys[0] - 25), right_prefix, fontsize=9)
            if captioned:
                page.insert_text(
                    (left, ys[0] - 35),
                    "Table B8. Continued" if column else "Table 11. Continued",
                    fontsize=9,
                )
            else:
                self.draw_grid(page, [left, left + 80, left + 260], ys)
            labels = ["44", "2-1"] if column == 0 else ["700A", "009"]
            for label, centre in zip(labels, centres, strict=True):
                page.insert_text((left + 15, centre + 4), label, fontsize=10)
                self.add_drawing(
                    page, records, left, centre, f"FOLLOW-{column}-{label}"
                )

    def assert_complete(self, result, payload, *, nonfinal=False, captioned=False):
        expected = {"Compound 73", "Compound 28", "Compound 44", "Compound 2-1"}
        if not nonfinal:
            expected |= {
                "Compound 901A",
                "Compound I-003B",
                "Compound 700A",
                "Compound 009",
            }
        self.assertEqual(
            {r["cpd"] for r in result["compound_catalog"]["entries"]},
            expected,
            payload["source_issues"],
        )
        self.assertEqual(coverage_errors(payload), [])
        saved = json.loads(json.dumps(payload))
        self.assertEqual(
            len(read_compound_catalog(saved, saved["compound_catalog"]["entries"])[0]),
            len(expected),
        )
        children = [
            s
            for s in payload["source_sections"]
            if s.get("source", {}).get("header_scope", {}).get("kind")
            == ("continued_unruled_columns" if captioned else "continued_ruled_columns")
        ]
        self.assertEqual(len(children), 2)
        self.assertEqual(
            {qualified_table_key(s["source"]["header_scope"]) for s in children},
            {"TABLE11", "TABLEB8"},
        )

    def test_both_physical_columns_continue_on_the_next_original_page(self):
        result, payload = self.run_case(mutate_document=self.continued_tables)
        self.assert_complete(result, payload)

    def test_both_logical_headers_can_anchor_their_own_actual_continued_frames(self):
        result, payload = self.run_case(
            ruled=False, mutate_document=self.continued_tables
        )
        self.assert_complete(result, payload)

    def test_both_explicit_original_captions_continue_without_printed_rules(self):
        result, payload = self.run_case(
            mutate_document=lambda d, r: self.continued_tables(d, r, captioned=True)
        )
        self.assert_complete(result, payload, captioned=True)

    def test_unruled_parallel_original_headers_anchor_their_own_captioned_parts(self):
        result, payload = self.run_case(
            ruled=False,
            mutate_document=lambda d, r: self.continued_tables(d, r, captioned=True),
        )
        self.assert_complete(result, payload, captioned=True)

    def test_nonfinal_role_is_retained_in_a_parallel_captioned_continuation(self):
        result, payload = self.run_case(
            nonfinal=True,
            mutate_document=lambda d, r: self.continued_tables(d, r, captioned=True),
        )
        self.assert_complete(result, payload, captioned=True, nonfinal=True)

    def test_parallel_nonfinal_role_survives_only_in_its_original_column(self):
        result, payload = self.run_case(
            nonfinal=True, mutate_document=self.continued_tables
        )
        self.assert_complete(result, payload, nonfinal=True)

    def test_two_same_page_physical_continuations_keep_separate_gap_evidence(self):
        result, payload = self.run_case(
            mutate_document=lambda d, r: self.continued_tables(d, r, same_page=True)
        )
        self.assert_complete(result, payload)

    def test_two_same_page_captioned_parts_keep_separate_original_parent_links(self):
        result, payload = self.run_case(
            mutate_document=lambda d, r: self.continued_tables(
                d, r, same_page=True, captioned=True
            )
        )
        self.assert_complete(result, payload, captioned=True)

    def test_unrelated_prefix_blocks_only_its_own_original_column(self):
        result, payload = self.run_case(
            mutate_document=lambda d, r: self.continued_tables(
                d, r, right_prefix="A different experiment was performed."
            )
        )
        self.assertEqual(
            {r["cpd"] for r in result["compound_catalog"]["entries"]},
            {
                "Compound 73",
                "Compound 28",
                "Compound 901A",
                "Compound I-003B",
                "Compound 44",
                "Compound 2-1",
            },
        )
        self.assertTrue(coverage_errors(payload))

    def test_independent_prior_column_experiment_does_not_stop_its_neighbour(self):
        result, payload = self.run_case(
            mutate_document=lambda d, r: self.continued_tables(
                d, r, prior_right_experiment=True
            )
        )
        self.assertEqual(
            {r["cpd"] for r in result["compound_catalog"]["entries"]},
            {
                "Compound 73",
                "Compound 28",
                "Compound 901A",
                "Compound I-003B",
                "Compound 44",
                "Compound 2-1",
                "Compound B80",
            },
        )
        self.assertTrue(coverage_errors(payload))

    def test_generated_scanned_continuations_replay_the_same_column_local_proof(self):
        for captioned in (False, True):
            for nonfinal in (False, True):
                with self.subTest(nonfinal=nonfinal, captioned=captioned):
                    result, payload = self.run_case(
                        raster=True,
                        nonfinal=nonfinal,
                        mutate_document=lambda d, r, captioned=captioned: (
                            self.continued_tables(d, r, captioned=captioned)
                        ),
                    )
                    self.assert_complete(
                        result, payload, nonfinal=nonfinal, captioned=captioned
                    )

    def test_same_page_unknown_right_gap_cannot_poison_the_left_gap(self):
        result, payload = self.run_case(
            mutate_document=lambda d, r: self.continued_tables(
                d,
                r,
                same_page=True,
                right_prefix="A different experiment was performed.",
            )
        )
        self.assertEqual(
            {r["cpd"] for r in result["compound_catalog"]["entries"]},
            {
                "Compound 73",
                "Compound 28",
                "Compound 901A",
                "Compound I-003B",
                "Compound 44",
                "Compound 2-1",
            },
        )
        self.assertTrue(coverage_errors(payload))

    def test_unowned_prefix_number_is_not_accepted_as_a_running_page_number(self):
        def prefix(document, records):
            self.continued_tables(document, records)
            document[1].insert_text((55, 45), "A000", fontsize=10)

        result, payload = self.run_case(mutate_document=prefix)
        self.assertEqual(
            {r["cpd"] for r in result["compound_catalog"]["entries"]},
            {
                "Compound 73",
                "Compound 28",
                "Compound 901A",
                "Compound I-003B",
                "Compound 700A",
                "Compound 009",
            },
        )
        self.assertTrue(coverage_errors(payload))

    def test_earlier_unowned_diagram_blocks_only_the_column_it_intersects(self):
        def prefix(document, records):
            self.continued_tables(document, records)
            self.add_drawing(document[1], records, 40, 45, "UNOWNED-PREFIX")

        result, payload = self.run_case(mutate_document=prefix)
        self.assertEqual(
            {r["cpd"] for r in result["compound_catalog"]["entries"]},
            {
                "Compound 73",
                "Compound 28",
                "Compound 901A",
                "Compound I-003B",
                "Compound 700A",
                "Compound 009",
            },
        )
        self.assertTrue(coverage_errors(payload))

    def test_missing_first_diagram_keeps_its_id_as_a_gap_without_shifting_rows(self):
        def missed(document, records):
            self.continued_tables(document, records)
            records[:] = [r for r in records if r["structure_id"] != "FOLLOW-0-44"]

        result, payload = self.run_case(mutate_document=missed)
        self.assertEqual(len(result["compound_catalog"]["entries"]), 7)
        self.assertNotIn(
            "Compound 44", {r["cpd"] for r in result["compound_catalog"]["entries"]}
        )
        self.assertEqual(
            next(
                r["structure_id"]
                for r in result["compound_catalog"]["entries"]
                if r["cpd"] == "Compound 2-1"
            ),
            "FOLLOW-0-2-1",
        )
        self.assertTrue(coverage_errors(payload))

    def test_no_detector_hits_in_one_continued_column_do_not_erase_its_frame(self):
        def missed(document, records):
            self.continued_tables(document, records)
            records[:] = [
                r for r in records if not r["structure_id"].startswith("FOLLOW-1-")
            ]

        result, payload = self.run_case(mutate_document=missed)
        self.assertEqual(len(result["compound_catalog"]["entries"]), 6)
        self.assertTrue(coverage_errors(payload))
        self.assertEqual(
            len(
                [
                    s
                    for s in payload["source_sections"]
                    if s.get("source", {}).get("header_scope", {}).get("kind")
                    == "continued_ruled_columns"
                ]
            ),
            2,
        )

    def test_rehashed_continuation_cannot_borrow_the_other_original_parent(self):
        _, payload = self.run_case(mutate_document=self.continued_tables)
        saved = json.loads(json.dumps(payload))
        roots = [
            s
            for s in saved["source_sections"]
            if s.get("source", {}).get("header_scope", {}).get("kind")
            == "original_ruled_columns"
        ]
        child = next(
            s
            for s in saved["source_sections"]
            if s.get("source", {}).get("header_scope", {}).get("kind")
            == "continued_ruled_columns"
        )
        old = child["region_id"]
        child["source"]["header_scope"].update(
            anchor_scope=roots[1]["source"]["header_scope"],
            parent_region_id=roots[1]["region_id"],
        )
        child["region_id"] = proof_id(child["source"])
        for row in saved["compound_catalog"]["entries"]:
            owner = (row.get("numbered_table_cell_evidence") or {}).get(
                "column_ownership", {}
            )
            if owner.get("source_anchor_id") == old:
                owner.update(
                    source_anchor_id=child["region_id"],
                    header_scope=child["source"]["header_scope"],
                )
        saved["source_reference_scope"] = reference_scope(
            saved["source_sections"],
            saved["source_reference_scope"]["original_pdf_sha256"],
        )
        saved["source_issues"] = []
        with self.assertRaises(ValueError):
            reference_issues(saved, saved["compound_catalog"]["entries"])


if __name__ == "__main__":
    unittest.main()
