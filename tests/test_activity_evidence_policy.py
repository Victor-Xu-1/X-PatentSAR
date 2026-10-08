"""Observed missing markers are data; classified-page extraction loss is not."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from patent_sar_extractor import contracts
from patent_sar_extractor.application.stage_activity import execute_activity
from patent_sar_extractor.core.activity_coverage import coverage_packet, source_record
from patent_sar_extractor.core.activity_join import (
    activity_evidence_errors,
    activity_order_and_map,
)
from patent_sar_extractor.core.qa_report import build_qa_report
from tests.test_source_led_export import export, run_fixture, save
from tests.test_source_led_pipeline import state_for


def payload(rows, seed_pages=None):
    seeds = ([0] if rows else []) if seed_pages is None else seed_pages
    regions = (
        [
            source_record(
                1,
                "text",
                None,
                "Controlled table",
                "Declared control cells",
                "parsed",
                "declared_text",
                len(rows),
            )
        ]
        if rows
        else []
    )
    return {
        **contracts.artifact_identity(
            contracts.ACTIVITY_SCHEMA, contracts.ACTIVITY_SCHEMA_VERSION
        ),
        "rows": rows,
        "coverage": coverage_packet(
            seeds, regions, [SimpleNamespace(page_no=1) for _ in rows]
        ),
    }


class ActivityEvidencePolicyTests(unittest.TestCase):
    def test_all_explicit_unavailable_markers_are_observed_data(self):
        for marker in ("ND", "N/A", "N.D.", "NT", "not tested", "—"):
            with self.subTest(marker=marker):
                self.assertEqual(
                    activity_evidence_errors(
                        payload(
                            [
                                {
                                    "cpd": "Compound 42",
                                    "activity_values": {"IC50 (nM)": marker},
                                }
                            ]
                        ),
                        [0],
                    ),
                    [],
                )

    def test_real_empty_cells_and_empty_buckets_remain_failure(self):
        for values in ({}, {"IC50": ""}):
            with self.subTest(values=values):
                self.assertTrue(
                    activity_evidence_errors(
                        payload([{"cpd": "Compound 42", "activity_values": values}]),
                        [0],
                    )
                )

    def test_malformed_fields_hard_fail(self):
        for values in ({"IC50": 17}, None, [], "ND"):
            with self.subTest(values=values), self.assertRaises(ValueError):
                activity_evidence_errors(
                    payload([{"cpd": "Compound 42", "activity_values": values}]), [0]
                )

    def test_good_observations_cannot_hide_empty_or_reviewed_rows(self):
        good = {"cpd": "Compound 42", "activity_values": {"IC50": "ND"}}
        for bad in (
            {"cpd": "Compound 42A", "activity_values": {}},
            {"cpd": "Compound 42A", "activity_values": {"IC50": "garbled"}},
            {
                "cpd": "Compound 42A",
                "activity_values": {"IC50": "ND"},
                "needs_review": True,
            },
        ):
            with self.subTest(bad=bad):
                self.assertTrue(activity_evidence_errors(payload([good, bad]), [0]))

    def test_compound_slashes_are_not_expanded_and_repeated_buckets_survive(self):
        self.assertTrue(
            activity_evidence_errors(
                payload([{"cpd": "Compound 1/2", "activity_values": {"IC50": "ND"}}]),
                [0],
            )
        )
        order, values = activity_order_and_map(
            [
                {
                    "cpd": "Compound 1-2-3A",
                    "activity_values": {"IC50": "ND"},
                    "cell_line_data": {"IC50": "N/A"},
                }
            ]
        )
        self.assertEqual(order, ["Compound 1-2-3A"])
        self.assertEqual(values[order[0]]["IC50"], "ND | N/A")

    def test_no_rows_need_actual_empty_classification_proof(self):
        self.assertEqual(activity_evidence_errors(payload([]), []), [])
        self.assertTrue(activity_evidence_errors(payload([], [0]), [0]))
        self.assertTrue(activity_evidence_errors(payload([]), None))

    def test_stage_uses_observation_evidence_not_active_numeric_membership(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = state_for(root, "activity")
            state.classification["activity_pages"] = [0]
            original = []

            def producer(pdf, classification, directory, **kwargs):
                data = payload(
                    [{"cpd": "Compound 42", "activity_values": {"IC50 (nM)": "ND"}}]
                )
                data["active_cpds"] = []
                path = Path(directory) / "activity_data.json"
                save(path, data)
                original.append(path.read_text())

            with patch(
                "patent_sar_extractor.application.stage_activity._run_activity_rules",
                side_effect=producer,
            ):
                execute_activity(state)
            self.assertEqual(state.pipeline_log["steps"]["activity"]["status"], "ok")
            self.assertEqual(state.scientific_errors, {})
            self.assertEqual(Path(state.act_json).read_text(), original[0])

    def test_all_nd_source_export_and_qa_use_same_evidence_rule(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_fixture(
                root,
                activities=[
                    {"cpd": "Compound 42", "activity_values": {"IC50 (nM)": "ND"}},
                    {"cpd": "Compound 42A", "activity_values": {"IC50 (nM)": "N/A"}},
                ],
            )
            result = export(root)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            qa = build_qa_report(str(root), patent_id="CONTROL")
            self.assertTrue(qa["acceptance"]["ok"], qa["acceptance"]["hard_errors"])


if __name__ == "__main__":
    unittest.main()
