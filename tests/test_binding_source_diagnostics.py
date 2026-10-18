"""Rejected original proposals survive in the one bounded diagnostic catalog."""

import copy
import tempfile
import unittest
from pathlib import Path

from patent_sar_extractor.core.binding_artifacts import write_binding_result
from patent_sar_extractor.core.binding_source_references import reference_issues
from patent_sar_extractor.core.source_role_observations import validate_role_catalog


class BindingSourceDiagnosticsTests(unittest.TestCase):
    def observe(self):
        proposal = {
            "cpd": "Compound 007B",
            "structure_id": "source-x",
            "page_no": 2,
            "binding_rule": "original_caption_cell",
            "exact_caption_evidence": {
                "bbox": [20, 40, 120, 65],
                "page_no": 2,
                "ownership": {"direction": None, "structure_cell": [20, 65, 120, 150]},
                "observations": [
                    {
                        "method": "cell_ocr_400dpi",
                        "raw_text": "Compound 007B",
                        "confidence": 0.62,
                    }
                ],
            },
        }
        temporary = tempfile.TemporaryDirectory(prefix="original-binding-diagnostics-")
        self.addCleanup(temporary.cleanup)
        payload = write_binding_result(
            Path(temporary.name),
            patent_id="CONTROLLED",
            bindings=[],
            catalog_bindings=[proposal],
            detected_style="original_cell_caption_heading",
            include_intermediates=False,
            total_structures=1,
            total_compound_blocks=0,
            table_pages=[1],
            table_covered_count=0,
            no_binding=[],
            unbound_pages=[],
            original_pdf_sha256="a" * 64,
        )
        return payload, proposal

    def test_unproved_original_proposal_is_retained_not_promoted_or_erased(self):
        payload, proposal = self.observe()
        self.assertEqual(payload["final_bindings"], [])
        issue = next(
            i
            for i in payload["source_issues"]
            if i["reason"] == "unproved_original_binding"
        )
        key = issue["evidence"]["source_diagnostic"]
        observed = payload["source_role_observations"][key]
        self.assertEqual(observed["status"], "unresolved")
        self.assertEqual(observed["proposal"], {**proposal, "patent_id": "CONTROLLED"})
        self.assertEqual(observed["structure_id"], "source-x")
        self.assertEqual(observed["page_no"], 2)
        self.assertEqual(observed["original_pdf_sha256"], "a" * 64)
        self.assertNotIn("proposal", issue["evidence"])
        self.assertTrue(payload["strict_coverage"]["unresolved_sources"])
        validate_role_catalog(
            payload["source_role_observations"], original_pdf_sha256="a" * 64
        )

    def test_diagnostic_mutation_foreign_source_and_promotion_are_rejected(self):
        payload, _proposal = self.observe()
        catalog = payload["source_role_observations"]
        self.assertTrue(catalog)
        with self.assertRaisesRegex(ValueError, "document"):
            validate_role_catalog(catalog, original_pdf_sha256="b" * 64)
        changed = copy.deepcopy(catalog)
        next(iter(changed.values()))["proposal"]["exact_caption_evidence"][
            "observations"
        ][0]["raw_text"] = "Changed raw source"
        with self.assertRaisesRegex(ValueError, "identity"):
            validate_role_catalog(changed)
        next(iter(catalog.values()))["status"] = "confirmed"
        with self.assertRaisesRegex(ValueError, "diagnostic"):
            validate_role_catalog(catalog)

    def test_clearing_saved_issue_flags_cannot_erase_unresolved_original_proposals(
        self,
    ):
        payload, _proposal = self.observe()
        payload["source_issues"] = []
        payload["strict_coverage"]["unresolved_sources"] = []
        problems = reference_issues(payload, [], required=True)
        self.assertEqual(
            [problem["reason"] for problem in problems], ["unproved_original_binding"]
        )
        self.assertEqual(problems[0]["structure_id"], "source-x")

    def test_missing_diagnostic_reference_cannot_become_a_resolved_issue(self):
        payload, _proposal = self.observe()
        payload["source_issues"][0]["evidence"]["source_diagnostic"] = "b" * 64
        with self.assertRaisesRegex(ValueError, "diagnostic reference"):
            reference_issues(payload, [], required=True)

    def test_rejected_linked_source_and_budget_limits_remain_explicit(self):
        from unittest.mock import patch

        from patent_sar_extractor.core.source_role_observations import (
            RoleObservationBuffer,
        )

        payload, _proposal = self.observe()
        observation = copy.deepcopy(
            next(iter(payload["source_role_observations"].values()))
        )
        linked = {"original_text": "Unproved continued original"}
        for _ in range(64):
            linked = {"previous": linked}
        observation["proposal"]["original_role_chain"] = linked
        buffer = RoleObservationBuffer()
        buffer.extend([observation])
        self.assertEqual(next(iter(buffer))["status"], "unresolved")
        oversized = copy.deepcopy(observation)
        oversized["proposal"]["raw_lines"] = ["q" * 4096] * 256
        with self.assertRaisesRegex(ValueError, "bounded region limit"):
            RoleObservationBuffer().extend([oversized])
        with (
            patch(
                "patent_sar_extractor.core.source_role_observations.MAX_ROLE_ATTEMPTS",
                1,
            ),
            self.assertRaisesRegex(ValueError, "inventory"),
        ):
            RoleObservationBuffer().extend([observation, observation])
