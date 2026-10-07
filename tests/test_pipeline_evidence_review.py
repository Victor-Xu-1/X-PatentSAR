"""One opt-in evidence review cannot rewrite chemistry or deterministic QA."""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

from patent_sar_extractor.application.evidence_review import review_source_evidence
from patent_sar_extractor.application.pipeline_context import PipelineContext
from patent_sar_extractor.application.progress import PipelineProgress
from patent_sar_extractor.integrations.llm.config import EvidenceResolutionConfig
from patent_sar_extractor.integrations.llm.evidence_resolution import (
    EvidenceResolution,
    ResolvedCandidate,
)


class PipelineEvidenceReviewTests(unittest.TestCase):
    def state(self, root):
        return PipelineContext(
            args=Namespace(pdf=str(root / "original.pdf")),
            progress=PipelineProgress(),
            base_dir=str(root),
            activity_payload={
                "rows": [
                    {
                        "needs_review": True,
                        "activity_sources": [
                            {
                                "page_no": 4,
                                "table_id": "Table 8",
                                "assay": "Unrelated target",
                                "header_region": {
                                    "page_no": 4,
                                    "bbox": [20, 30, 100, 40],
                                },
                                "raw_caption": "Private preceding prose must remain local",
                                "cells": [
                                    {
                                        "field": "unknown field",
                                        "raw_header": "unknown original header",
                                        "physical_column": 2,
                                        "bbox": [40, 50, 80, 65],
                                    }
                                ],
                            }
                        ],
                    }
                ]
            },
            scientific_errors={"bind": ["unresolved original owner"]},
        )

    def test_default_off_never_calls_client_or_writes_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with (
                patch(
                    "patent_sar_extractor.application.evidence_review.get_evidence_resolution_config",
                    return_value=EvidenceResolutionConfig(),
                ),
                patch(
                    "patent_sar_extractor.application.evidence_review.resolve_evidence"
                ) as client,
            ):
                self.assertIsNone(
                    review_source_evidence(self.state(root), ["unknown header"])
                )
            client.assert_not_called()
            self.assertEqual(list(root.iterdir()), [])

    def test_config_without_disclosure_consent_does_not_read_original_or_call(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with (
                patch(
                    "patent_sar_extractor.application.evidence_review.get_evidence_resolution_config",
                    return_value=EvidenceResolutionConfig(mode="on-error"),
                ),
                patch(
                    "patent_sar_extractor.application.evidence_review.resolve_evidence"
                ) as client,
            ):
                report = review_source_evidence(self.state(root), ["unknown header"])
            self.assertEqual(report["reason"], "data_consent_required")
            client.assert_not_called()
            self.assertEqual(list(root.iterdir()), [])

    def test_enabled_review_deduplicates_columns_and_preserves_formal_errors(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = self.state(root)
            state.activity_payload["rows"] *= 100
            prior = copy.deepcopy((state.activity_payload, state.scientific_errors))
            policy = EvidenceResolutionConfig(
                mode="on-error",
                data_consent=True,
                endpoint="https://model.invalid/v1",
                model="controlled",
                api_key="controlled-test-only",
            )
            with (
                patch(
                    "patent_sar_extractor.application.evidence_review.get_evidence_resolution_config",
                    return_value=policy,
                ),
                patch(
                    "patent_sar_extractor.application.evidence_review._pdf_sha256",
                    return_value="a" * 64,
                ),
                patch(
                    "patent_sar_extractor.application.evidence_review.resolve_evidence",
                    return_value=EvidenceResolution("resolved", "abstain"),
                ) as client,
            ):
                report = review_source_evidence(state, ["unknown header"])
            client.assert_called_once()
            request, budget = client.call_args.args
            self.assertEqual(len(request.candidates), 1)
            self.assertNotIn("Private preceding prose", str(request.observations))
            self.assertEqual(budget.max_calls, 8)
            self.assertEqual(report["outcome"], "unresolved")
            self.assertEqual((state.activity_payload, state.scientific_errors), prior)
            receipt = json.loads((root / "evidence_resolution_review.json").read_text())
            self.assertFalse(receipt["formal_acceptance_changed"])
            self.assertEqual(receipt["authority"], "advisory")

    def test_physical_columns_and_incomplete_reference_sets_remain_distinct(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = self.state(root)
            cells = state.activity_payload["rows"][0]["activity_sources"][0]["cells"]
            cells.append({**cells[0], "physical_column": 3})
            policy = EvidenceResolutionConfig(
                mode="on-error",
                data_consent=True,
                endpoint="https://model.invalid/v1",
                model="controlled",
                api_key="controlled-test-only",
            )

            def incomplete(request, budget, **_):
                self.assertEqual(len(request.candidates), 2)
                self.assertNotEqual(
                    request.candidates[0].candidate_id,
                    request.candidates[1].candidate_id,
                )
                candidate = request.candidates[0]
                return EvidenceResolution(
                    "resolved",
                    "partial",
                    (
                        ResolvedCandidate(
                            candidate.candidate_id, candidate.observation_ids[:1]
                        ),
                    ),
                )

            with (
                patch(
                    "patent_sar_extractor.application.evidence_review.get_evidence_resolution_config",
                    return_value=policy,
                ),
                patch(
                    "patent_sar_extractor.application.evidence_review._pdf_sha256",
                    return_value="a" * 64,
                ),
                patch(
                    "patent_sar_extractor.application.evidence_review.resolve_evidence",
                    side_effect=incomplete,
                ),
            ):
                report = review_source_evidence(state, ["unknown header"])
            self.assertEqual(report["reason"], "required_evidence_missing")
            self.assertEqual(report["outcome"], "failed")

    def test_optional_receipt_failure_cannot_erase_scientific_findings(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = self.state(root)
            prior = copy.deepcopy(state.scientific_errors)
            policy = EvidenceResolutionConfig(
                mode="quality",
                data_consent=True,
                endpoint="https://model.invalid/v1",
                model="controlled",
                api_key="controlled-test-only",
            )
            with (
                patch(
                    "patent_sar_extractor.application.evidence_review.get_evidence_resolution_config",
                    return_value=policy,
                ),
                patch(
                    "patent_sar_extractor.application.evidence_review._pdf_sha256",
                    return_value="a" * 64,
                ),
                patch(
                    "patent_sar_extractor.application.evidence_review.resolve_evidence",
                    return_value=EvidenceResolution("resolved", "abstain"),
                ),
                patch(
                    "patent_sar_extractor.application.evidence_review.write_json_atomic",
                    side_effect=OSError("controlled publication failure"),
                ),
            ):
                report = review_source_evidence(state, [])
            self.assertEqual(report["reason"], "receipt_publication_failed")
            self.assertEqual(state.scientific_errors, prior)


if __name__ == "__main__":
    unittest.main()
