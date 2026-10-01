"""The selected package wins without replacing scientific runtime dependencies."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from patent_sar_extractor.core.env_runner import run_snippet


class WorkerBootstrapTests(unittest.TestCase):
    def test_current_package_selected_without_parent_binary_dependency_leak(self):
        bootstrap = (
            Path(__file__).resolve().parents[1]
            / "src/patent_sar_extractor/worker_bootstrap.py"
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            stale = root / "stale"
            stale.mkdir()
            (stale / "patent_sar_extractor").mkdir()
            (stale / "patent_sar_extractor/__init__.py").write_text(
                "raise RuntimeError('stale package executed')\n"
            )
            selected_parent = root / "selected-site-packages"
            selected = selected_parent / "patent_sar_extractor"
            selected.mkdir(parents=True)
            (selected / "__init__.py").write_text(
                "marker = 'selected-current-package'\n"
            )
            (selected_parent / "runtime_dependency.py").write_text(
                "raise RuntimeError('foreign dependency leaked')\n"
            )
            (stale / "runtime_dependency.py").write_text(
                "marker = 'native-scientific-runtime'\n"
            )
            code = f"import sys,runpy,json\nsys.path.insert(0,{str(stale)!r})\nrunpy.run_path({str(bootstrap)!r})['bootstrap_package'](__import__('pathlib').Path({str(selected)!r}))\nimport patent_sar_extractor,runtime_dependency\nprint(json.dumps([patent_sar_extractor.marker,runtime_dependency.marker]))\n"
            result = subprocess.run(
                [sys.executable, "-c", code],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                json.loads(result.stdout),
                ["selected-current-package", "native-scientific-runtime"],
            )

    def test_snippet_imports_exact_caller_package(self):
        from unittest.mock import patch

        import patent_sar_extractor

        with patch.dict(os.environ, {"PATENTSAR_BASE_PYTHON": sys.executable}):
            result = run_snippet(
                "base",
                "import patent_sar_extractor\nprint(patent_sar_extractor.__file__)\n",
                timeout=10,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            Path(result.stdout.strip()).resolve(),
            Path(patent_sar_extractor.__file__).resolve(),
        )
