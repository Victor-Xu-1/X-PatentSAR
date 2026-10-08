from __future__ import annotations

import ast
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "src" / "patent_sar_extractor"


class ArchitectureContractTests(unittest.TestCase):
    def test_llm_qa_is_explicitly_skipped_and_never_overwrites_formal_report(self) -> None:
        from patent_sar_extractor.integrations.llm import advisory_qa as llm_qa_module

        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            formal_report = output_dir / "final_qa_report.md"
            formal_report.write_text("formal report\n", encoding="utf-8")

            from patent_sar_extractor.integrations.llm.config import EvidenceResolutionConfig

            with patch.object(llm_qa_module, "get_evidence_resolution_config", return_value=EvidenceResolutionConfig()):
                result = llm_qa_module.run_advisory_qa(str(output_dir))

            self.assertEqual(result["status"], "skipped_policy")
            self.assertEqual(result["authority"], "advisory")
            self.assertEqual(formal_report.read_text(encoding="utf-8"), "formal report\n")
            self.assertTrue((output_dir / "llm_qa_report.json").is_file())
            self.assertTrue((output_dir / "llm_qa_report.md").is_file())

    def test_llm_client_has_bounded_retry_and_validates_structured_output(self) -> None:
        from patent_sar_extractor.integrations.llm import client as llm_client

        config = {
            "model": "test-model",
            "endpoint": "https://llm.invalid/v1",
            "api_key": "test-only-key",
            "timeout": 1,
            "cache_path": "",
        }
        with patch.object(llm_client, "get_llm_config", return_value=config), patch.object(
            llm_client, "bounded_post",
            side_effect=[llm_client.requests.exceptions.Timeout(), b'{"choices":[{"finish_reason":"stop","message":{"content":"{\\"ok\\":true}"}}]}'],
        ) as post, patch.object(llm_client.time, "sleep") as sleep:
            result = llm_client.llm_chat([{"role": "user", "content": "test"}], cache=False, max_retries=1)

        self.assertEqual(result, '{"ok":true}')
        self.assertEqual(post.call_count, 2)
        sleep.assert_not_called()

        key_a = llm_client._cache_key([], "model", 0.0, "https://one.invalid", 100)
        key_b = llm_client._cache_key([], "model", 0.0, "https://two.invalid", 100)
        key_c = llm_client._cache_key([], "model", 0.0, "https://one.invalid", 200)
        self.assertEqual(len({key_a, key_b, key_c}), 3)

    def test_advisory_qa_cannot_veto_formal_acceptance(self) -> None:
        from patent_sar_extractor.application.qa_policy import compose_qa_decision

        deterministic = {
            "ok": True,
            "warnings": [],
            "acceptance": {"ok": True, "hard_errors": []},
        }
        advisory = {
            "authority": "advisory",
            "status": "completed",
            "assessment": "review",
            "warnings": ["Model requests a manual review."],
        }

        decision = compose_qa_decision(deterministic, advisory)

        self.assertTrue(decision["ok"])
        self.assertTrue(decision["acceptance"]["ok"])
        self.assertEqual(decision["warnings"], [])
        self.assertEqual(decision["advisory"]["warnings"], advisory["warnings"])

    def test_domain_core_does_not_import_application_or_integration_layers(self) -> None:
        forbidden = (
            "patent_sar_extractor.application",
            "patent_sar_extractor.integrations",
            "patent_sar_extractor.orchestration",
        )
        offenders: list[str] = []
        for path in sorted((SOURCE_ROOT / "core").rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            if any(name in text for name in forbidden):
                offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual(offenders, [])

    def test_cli_contains_presentation_logic_only(self) -> None:
        tree = ast.parse((SOURCE_ROOT / "cli.py").read_text(encoding="utf-8"))
        functions = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
        forbidden = {
            "cmd_run",
            "_activity_acceptance_errors",
            "_binding_acceptance_errors",
            "_smiles_acceptance_errors",
            "_gpu_env_extra",
            "_write_step_manifest",
        }
        self.assertEqual(functions & forbidden, set())

    def test_smiles_artifact_requires_current_production_envelope(self) -> None:
        from patent_sar_extractor.smiles_artifact import (
            DIAGNOSTIC_SMILES_MODE,
            build_smiles_artifact,
            smiles_artifact_is_current,
        )

        records = [{"cpd_id": "Compound 1", "canonical_smiles": "CCO"}]
        production = build_smiles_artifact(records)
        diagnostic = build_smiles_artifact(records, execution_mode=DIAGNOSTIC_SMILES_MODE)

        self.assertTrue(smiles_artifact_is_current(production))
        self.assertFalse(smiles_artifact_is_current(records))
        self.assertFalse(smiles_artifact_is_current(diagnostic))
        self.assertTrue(smiles_artifact_is_current(diagnostic, require_production=False))


if __name__ == "__main__":
    unittest.main()
