from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from patent_sar_extractor.cli import build_parser
from patent_sar_extractor.integrations.llm import advisory_qa


class AdvisoryPolicyTests(unittest.TestCase):
    def test_explicit_policy_never_reads_credentials_or_calls_model(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            formal = root / "final_qa_report.json"
            formal.write_text('{"acceptance":{"ok":false},"ok":false}')
            original = formal.read_bytes()
            with (
                patch.object(
                    advisory_qa,
                    "get_evidence_resolution_config",
                    side_effect=AssertionError("must not read credentials"),
                ),
                patch.object(advisory_qa, "resolve_evidence") as model,
            ):
                result = advisory_qa.run_advisory_qa(directory, enabled=False)
            model.assert_not_called()
            self.assertEqual(result["status"], "skipped_by_operator")
            self.assertEqual(result["authority"], "advisory")
            self.assertEqual(formal.read_bytes(), original)
            self.assertEqual(
                json.loads((root / "llm_qa_report.json").read_text())["status"],
                "skipped_by_operator",
            )
            self.assertTrue((root / "llm_qa_report.md").is_file())

    def test_cli_exposes_opt_out_without_changing_strict_acceptance(self) -> None:
        args = build_parser().parse_args(
            ["run", "--pdf", "input.pdf", "--skip-advisory-qa"]
        )
        self.assertTrue(args.skip_advisory_qa)
        self.assertTrue(args.strict_gates)
        self.assertFalse(
            build_parser().parse_args(["run", "--pdf", "input.pdf"]).skip_advisory_qa
        )


if __name__ == "__main__":
    unittest.main()
