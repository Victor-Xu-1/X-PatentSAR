from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from patent_sar_extractor import cli
from patent_sar_extractor.contracts import (
    BINDINGS_SCHEMA_VERSION,
    COMMAND_NAME,
    DISTRIBUTION_NAME,
    PAGE_CLASSIFICATION_SCHEMA_VERSION,
    PIPELINE_CONTRACT_VERSION,
    PRODUCT_NAME,
    QA_REPORT_SCHEMA_VERSION,
    RULESET_VERSION,
    RUN_SUMMARY_SCHEMA_VERSION,
    SMILES_SCHEMA_VERSION,
    __version__,
)
from patent_sar_extractor.paths import config_files


class StandalonePackagingTests(unittest.TestCase):
    @staticmethod
    def _source_env() -> dict[str, str]:
        env = os.environ.copy()
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(SOURCE_ROOT), existing]))
        return env

    def test_version_command_uses_product_version(self) -> None:
        proc = subprocess.run(
            [sys.executable, "-m", "patent_sar_extractor", "--version"],
            cwd=ROOT,
            env=self._source_env(),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn(PRODUCT_NAME, proc.stdout)
        self.assertIn(f"v{__version__}", proc.stdout)
        self.assertIn(__version__, proc.stdout)

    def test_run_help_documents_strict_default_and_partial_override(self) -> None:
        proc = subprocess.run(
            [sys.executable, "-m", "patent_sar_extractor", "run", "--help"],
            cwd=ROOT,
            env=self._source_env(),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("standalone default", proc.stdout)
        self.assertIn("--allow-partial", proc.stdout)

    def test_run_parser_is_strict_by_default(self) -> None:
        captured = []
        with (
            patch.object(
                cli, "cmd_run", side_effect=lambda args: captured.append(args)
            ),
            patch.object(
                sys, "argv", [COMMAND_NAME, "run", "--pdf", "/tmp/example.pdf"]
            ),
        ):
            cli.main()
        self.assertTrue(captured[0].strict_gates)

        captured.clear()
        with (
            patch.object(
                cli, "cmd_run", side_effect=lambda args: captured.append(args)
            ),
            patch.object(
                sys,
                "argv",
                [COMMAND_NAME, "run", "--pdf", "/tmp/example.pdf", "--allow-partial"],
            ),
        ):
            cli.main()
        self.assertFalse(captured[0].strict_gates)

    def test_external_config_directory_is_honored_in_new_process(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            env = self._source_env()
            env["PATENTSAR_CONFIG_DIR"] = temp
            proc = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "from patent_sar_extractor.paths import config_files; print(config_files('llm.yaml')[1])",
                ],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(Path(proc.stdout.strip()), Path(temp) / "llm.yaml")

    def test_config_filename_rejects_path_traversal(self) -> None:
        with self.assertRaises(ValueError):
            config_files("../llm.yaml")

    def test_production_code_has_no_synon_runtime_dependency(self) -> None:
        forbidden = (".synon", "SYNON_API_BASE", "SYNON_AUTH_TOKEN")
        for path in (SOURCE_ROOT / "patent_sar_extractor").rglob("*.py"):
            text = path.read_text(encoding="utf-8-sig")
            for marker in forbidden:
                self.assertNotIn(marker, text, f"{marker!r} found in {path}")

    def test_shell_wrapper_is_valid_bash(self) -> None:
        launcher = ROOT / "run_patent_sar.sh"
        proc = subprocess.run(
            ["bash", "-n", str(launcher)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)

        text = launcher.read_text(encoding="utf-8")
        self.assertNotIn("--auto-repair", text)
        self.assertNotIn("--smiles-workers 2", text)

        env = os.environ.copy()
        env["PATENTSAR_PYTHON"] = sys.executable
        help_proc = subprocess.run(
            ["bash", str(launcher), "placeholder.pdf", "--help"],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(help_proc.returncode, 0, help_proc.stderr)
        self.assertIn("--gpu-mode", help_proc.stdout)

    def test_product_identity_is_consistent(self) -> None:
        import tomllib

        metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        project = metadata["project"]
        self.assertEqual(PRODUCT_NAME, "X-PatentSAR")
        self.assertEqual(DISTRIBUTION_NAME, "x-patentsar")
        self.assertEqual(COMMAND_NAME, "x-patentsar")
        self.assertEqual(__version__, "0.1.0")
        self.assertEqual(PIPELINE_CONTRACT_VERSION, "2.0.0")
        self.assertEqual(RULESET_VERSION, "2.0.2")
        self.assertEqual(RUN_SUMMARY_SCHEMA_VERSION, 1)
        self.assertEqual(PAGE_CLASSIFICATION_SCHEMA_VERSION, 2)
        self.assertEqual(BINDINGS_SCHEMA_VERSION, 2)
        self.assertEqual(SMILES_SCHEMA_VERSION, 1)
        self.assertEqual(QA_REPORT_SCHEMA_VERSION, 2)
        self.assertEqual(project["name"], DISTRIBUTION_NAME)
        self.assertIn(COMMAND_NAME, project["scripts"])
        package_find = metadata["tool"]["setuptools"]["packages"]["find"]
        self.assertEqual(package_find["where"], ["src"])
        self.assertEqual(package_find["include"], ["patent_sar_extractor*"])
        self.assertEqual(
            metadata["tool"]["setuptools"]["dynamic"]["version"]["attr"],
            "patent_sar_extractor.contracts.__version__",
        )

        commands = set(cli.build_parser()._subparsers._group_actions[0].choices)
        self.assertEqual(
            commands,
            {
                "run",
                "classify",
                "excerpt",
                "activity",
                "smiles",
                "validate",
                "score",
                "health",
                "check-envs",
                "qa",
                "serve",
                "import-run",
            },
        )


if __name__ == "__main__":
    unittest.main()
