"""Only fully executed current QA rejection permits qualified enrichment."""

import tempfile
import unittest
from pathlib import Path

from patent_sar_extractor import contracts as c
from patent_sar_extractor.artifact_io import write_json_atomic
from patent_sar_extractor.web.core_research_policy import completed_qa_rejection


class CoreResearchPolicyTests(unittest.TestCase):
    def packet(self):
        return {
            **c.artifact_identity(c.RUN_SUMMARY_SCHEMA, c.RUN_SUMMARY_SCHEMA_VERSION),
            "status": "failed_qa",
            "main_chain": list(c.CORE_STAGE_ORDER),
            "steps": {
                **{s: {"status": "ok"} for s in c.CORE_STAGE_ORDER},
                "qa": {
                    "status": "failed",
                    "strict_acceptance_ok": False,
                    "hard_errors": ["Controlled graph rejection"],
                },
            },
        }

    def evaluate(self, packet):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_json_atomic(root / "pipeline_summary.json", packet)
            return completed_qa_rejection(root)

    def test_current_terminal_qa_rejection_is_research_not_success(self):
        self.assertTrue(self.evaluate(self.packet()))

    def test_technical_interruption_running_or_old_evidence_cannot_enter_research(self):
        for mutation in ("pending", "identity", "missing", "status"):
            with self.subTest(mutation=mutation):
                value = self.packet()
                if mutation == "pending":
                    value["steps"]["smiles"]["status"] = "running"
                elif mutation == "identity":
                    value["ruleset"]["version"] = "2.0.4"
                elif mutation == "missing":
                    del value["steps"]["final"]
                else:
                    value["status"] = "failed"
                self.assertFalse(self.evaluate(value))
