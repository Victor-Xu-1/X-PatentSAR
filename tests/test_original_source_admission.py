"""A proposal or legacy sequence flag is not current original-source proof."""

import tempfile
import unittest
from pathlib import Path

from test_caption_reading_semantics import binding as caption_binding

from patent_sar_extractor.core.binding_artifacts import write_binding_result
from patent_sar_extractor.core.binding_catalog import compound_catalog
from patent_sar_extractor.core.binding_spatial import (
    _extract_authoritative_structure_table_sequence_bindings,
)
from patent_sar_extractor.core.catalog_reader import read_catalog_entries
from patent_sar_extractor.core.pipeline_rules import STRONG_BINDING_RULES
from patent_sar_extractor.core.series_table_binding import pair_series_table


def legacy_series():
    from test_series_table_binding import SeriesTableBindingTests

    structures, lines = SeriesTableBindingTests()._table([101, 102, 103, 104, 105, 106])
    proposed = pair_series_table(structures, [9], lines, None)
    return _extract_authoritative_structure_table_sequence_bindings(
        structures, {}, [], {}, ocr_line_map=lines, series_result=proposed
    )


def original_caption(label="I-008A"):
    row = caption_binding([{"method": "native_cell", "text": "Compound " + label}])
    row["cpd"] = "Compound " + label
    return row


def publish(directory, rows):
    return write_binding_result(
        directory,
        patent_id="CONTROLLED-ADMISSION",
        bindings=[],
        catalog_bindings=rows,
        detected_style="original_cell_caption_heading",
        include_intermediates=False,
        total_structures=len(rows),
        total_compound_blocks=0,
        table_pages=[],
        table_covered_count=0,
        no_binding=[],
        unbound_pages=[],
    )


class OriginalSourceAdmissionTests(unittest.TestCase):
    def test_retired_rule_names_and_saved_success_flags_do_not_grant_source_authority(
        self,
    ):
        current = {
            "numbered_structure_table_cell",
            "original_caption_cell",
            "original_heading_standalone",
        }
        for rule in STRONG_BINDING_RULES - current:
            with self.subTest(rule=rule):
                row = {
                    **legacy_series()[0],
                    "binding_rule": rule,
                    "accuracy_status": "confirmed",
                    "fail_closed": False,
                }
                self.assertEqual(compound_catalog([row], [])["entries"], [])

    def test_real_legacy_series_proposals_are_not_confirmed_current_sources(self):
        rows = legacy_series()
        self.assertEqual(len(rows), 6)
        self.assertTrue(all("exact_caption_evidence" not in row for row in rows))
        self.assertEqual(compound_catalog(rows, [])["entries"], [])

    def test_writer_retains_each_unproved_proposal_as_an_explicit_source_issue(self):
        rows = legacy_series()
        with tempfile.TemporaryDirectory(prefix="source-admission-") as temporary:
            payload = publish(Path(temporary), rows)
        self.assertEqual(payload["final_bindings"], [])
        self.assertEqual(
            {issue["cpd"] for issue in payload["source_issues"]},
            {row["cpd"] for row in rows},
        )
        self.assertTrue(
            all(
                issue["reason"] == "unproved_original_binding"
                for issue in payload["source_issues"]
            )
        )

    def test_current_reader_rejects_legacy_flags_even_if_saved_issues_are_cleared(self):
        with tempfile.TemporaryDirectory(prefix="source-admission-") as temporary:
            payload = publish(Path(temporary), [original_caption()])
        payload["compound_catalog"]["entries"] = legacy_series()
        payload["final_bindings"] = list(payload["compound_catalog"]["entries"])
        payload["source_issues"] = []
        with self.assertRaises(ValueError):
            read_catalog_entries(payload)

    def test_complete_original_caption_keeps_full_i_prefix_zeros_and_suffix(self):
        with tempfile.TemporaryDirectory(prefix="source-admission-") as temporary:
            payload = publish(Path(temporary), [original_caption()])
        rows, _ = read_catalog_entries(payload)
        self.assertEqual([row["cpd"] for row in rows], ["Compound I-008A"])
        self.assertEqual(payload["source_issues"], [])

    def test_historical_sequence_remains_readable_but_is_not_retagged_current(self):
        with tempfile.TemporaryDirectory(prefix="source-admission-") as temporary:
            payload = publish(Path(temporary), [original_caption()])
        payload["schema"] = {
            **payload["schema"],
            "version": payload["schema"]["version"] - 1,
        }
        payload["compound_catalog"]["entries"] = legacy_series()
        rows, _ = read_catalog_entries(payload)
        self.assertEqual(len(rows), 6)
        self.assertNotIn("exact_caption_evidence", rows[0])


if __name__ == "__main__":
    unittest.main()
