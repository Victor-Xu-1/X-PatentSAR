"""Native source controls must not acquire a Web test-client dependency."""

import os
import subprocess
import sys
import unittest
from pathlib import Path


class RecognitionFixtureIsolationTests(unittest.TestCase):
    def test_native_source_controls_import_without_web_test_transport(self):
        script = """
import importlib.abc
import sys

class NoWebTestTransport(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in {
            'fastapi.testclient', 'starlette.testclient', 'test_web_support',
            'test_uniform_recognition',
        } or fullname.partition('.')[0] in {'httpx', 'httpx2'}:
            raise RuntimeError('Native source fixture imports Web test transport: ' + fullname)

sys.meta_path.insert(0, NoWebTestTransport())
import test_heading_reprint_sources
import test_heading_column_scope
print('Native source controls import without Web test transport')
"""
        repository = Path(__file__).resolve().parent.parent
        env = {
            **os.environ,
            "PYTHONPATH": os.pathsep.join(
                filter(
                    None,
                    [
                        str(repository / "tests"),
                        str(repository),
                        os.environ.get("PYTHONPATH", ""),
                    ],
                )
            ),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=repository,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("without Web test transport", result.stdout)
