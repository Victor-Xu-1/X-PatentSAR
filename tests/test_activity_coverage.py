"""Coverage regressions: no detected/declared activity source may disappear."""

from __future__ import annotations

import unittest
from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import Mock, patch

from patent_sar_extractor.contracts import (
    ACTIVITY_SCHEMA,
    ACTIVITY_SCHEMA_VERSION,
    artifact_identity,
)
from patent_sar_extractor.core import activity_coordinates as coordinates
from patent_sar_extractor.core.activity_join import activity_evidence_errors
from patent_sar_extractor.core.activity_models import ActivityRow


class ActivityCoverageTests(unittest.TestCase):
    def payload(self, rows, coverage):
        return {
            **artifact_identity(ACTIVITY_SCHEMA, ACTIVITY_SCHEMA_VERSION),
            "rows": [asdict(row) for row in rows],
            "coverage": coverage,
        }

    def test_unparsed_second_grid_is_retained_even_when_first_table_has_rows(self):
        region = {"xs": [20, 160, 300], "ys": [150, 180, 210, 240]}
        matrices = [
            [["Example", "IC50 (nM)"], ["1", "1.2"], ["2", "2.4"]],
            [["Material code", "IC50 (nM)"], ["1", "0.3"], ["2", "0.4"]],
        ]
        rows = [
            ActivityRow(
                cpd="Compound 1", activity_values={"IC50 (nM)": "1.2"}, page_no=1
            )
        ]
        resolver = Mock(return_value=None)
        with (
            patch.object(
                coordinates, "detect_ruled_table_regions", return_value=[region]
            ),
            patch.object(coordinates, "page_tokens", return_value=[]),
            patch.object(coordinates, "table_matrix", side_effect=matrices),
            patch.object(
                coordinates,
                "_prefix",
                side_effect=["Table 1. Binding activity", "Table 2. Binding activity"],
            ),
            patch.object(coordinates, "extract_tables", return_value=[]),
            patch.object(coordinates, "parse_grid", return_value=rows),
        ):
            parsed = coordinates.extract_coordinate_tables(
                [SimpleNamespace(number=0), SimpleNamespace(number=1)],
                [0, 1],
                header_resolver=resolver,
            )
        self.assertEqual(len(parsed.rows), 1)
        resolver.assert_called_once()
        self.assertEqual(
            [item["status"] for item in parsed.coverage], ["parsed", "unresolved"]
        )
        self.assertEqual(parsed.coverage[1]["page_no"], 2)
        self.assertEqual(parsed.coverage[1]["reason"], "unsupported_header")

    def test_partial_rows_cannot_mask_unresolved_source_or_page(self):
        from patent_sar_extractor.core.activity_coverage import (
            coverage_packet,
            source_record,
        )

        rows = [
            ActivityRow(cpd="Compound 1", activity_values={"Ki (nM)": "1.2"}, page_no=1)
        ]
        regions = [
            source_record(
                1,
                "grid",
                [20, 50, 300, 200],
                "Table 1",
                "Example Ki",
                "parsed",
                "original_cells",
                1,
            ),
            source_record(
                2,
                "grid",
                [20, 50, 300, 200],
                "Table 2",
                "Material Ki",
                "unresolved",
                "unsupported_header",
                0,
            ),
        ]
        coverage = coverage_packet([0, 1], regions, rows)
        errors = activity_evidence_errors(self.payload(rows, coverage), [0, 1])
        self.assertTrue(any("Unresolved activity source" in error for error in errors))
        self.assertTrue(any("p2" in error for error in errors))

    def test_missing_seed_is_not_inferred_complete_from_other_rows(self):
        from patent_sar_extractor.core.activity_coverage import (
            coverage_packet,
            source_record,
        )

        rows = [
            ActivityRow(cpd="Compound 1", activity_values={"Ki (nM)": "1.2"}, page_no=1)
        ]
        region = source_record(
            1, "text", None, "Table 1", "Example Ki", "parsed", "declared_text", 1
        )
        packet = coverage_packet([0, 1], [region], rows)
        errors = activity_evidence_errors(self.payload(rows, packet), [0, 1])
        self.assertTrue(any("p2" in error for error in errors))

    def test_empty_classification_is_explicit_zero_work_not_document_rescan(self):
        from patent_sar_extractor.core.activity_coverage import coverage_packet

        payload = self.payload([], coverage_packet([], [], []))
        self.assertEqual(activity_evidence_errors(payload, []), [])

    def test_foreign_seed_proof_and_duplicate_region_fail_closed(self):
        from patent_sar_extractor.core.activity_coverage import (
            coverage_packet,
            source_record,
        )

        rows = [
            ActivityRow(cpd="Compound 1", activity_values={"Ki (nM)": "1.2"}, page_no=1)
        ]
        region = source_record(
            1, "text", None, "Table 1", "Example Ki", "parsed", "declared_text", 1
        )
        packet = coverage_packet([0], [region], rows)
        with self.assertRaises(ValueError):
            activity_evidence_errors(self.payload(rows, packet), [0, 1])
        packet["regions"].append(dict(region))
        with self.assertRaises(ValueError):
            activity_evidence_errors(self.payload(rows, packet), [0])
