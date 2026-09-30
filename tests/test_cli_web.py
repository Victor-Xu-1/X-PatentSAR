from __future__ import annotations

import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

from patent_sar_extractor.application.web_commands import frontend_path, web_state_path
from patent_sar_extractor.cli import build_parser
from patent_sar_extractor.paths import PACKAGE_ROOT


class WebCLIBoundaryTests(unittest.TestCase):
    def test_web_listener_rejects_public_hosts_and_invalid_ports(self) -> None:
        parser = build_parser()
        for options in (
            ("--host", "0.0.0.0"),
            ("--host", "example.com"),
            ("--port", "0"),
            ("--port", "65536"),
            ("--port", "abc"),
        ):
            with (
                self.subTest(options=options),
                redirect_stderr(io.StringIO()),
                self.assertRaises(SystemExit) as error,
            ):
                parser.parse_args(["serve", *options])
            self.assertEqual(error.exception.code, 2)
        args = parser.parse_args(["serve", "--port", "18765"])
        self.assertEqual((args.host, args.port), ("127.0.0.1", 18765))

    def test_job_lifetime_has_finite_bounds_and_supports_large_patents(self) -> None:
        parser = build_parser()
        self.assertEqual(parser.parse_args(["serve"]).job_timeout_hours, 24.0)
        for value in ("0", "25", "nan", "inf", "abc"):
            with (
                self.subTest(value=value),
                redirect_stderr(io.StringIO()),
                self.assertRaises(SystemExit),
            ):
                parser.parse_args(["serve", "--job-timeout-hours", value])

    def test_state_configuration_priority_and_safe_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict(
                os.environ, {"PATENTSAR_WEB_STATE_DIR": str(root / "env")}, clear=False
            ):
                self.assertEqual(web_state_path(), root / "env")
                self.assertEqual(
                    web_state_path(str(root / "explicit")), root / "explicit"
                )
            for target in ("/", str(Path.home()), str(PACKAGE_ROOT / "web" / "state")):
                with self.subTest(target=target), self.assertRaises(ValueError):
                    web_state_path(target)
            (root / ".git").mkdir()
            with self.assertRaisesRegex(ValueError, "Git checkouts"):
                web_state_path(str(root / "runtime"))

    def test_production_requires_built_frontend_and_api_mode_is_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            assets = Path(directory)
            with self.assertRaisesRegex(ValueError, "Web assets are missing"):
                frontend_path(directory)
            (assets / "index.html").write_text("<html></html>")
            self.assertEqual(frontend_path(directory), assets)
            self.assertIsNone(frontend_path(api_only=True))
            with self.assertRaisesRegex(ValueError, "cannot be combined"):
                frontend_path(directory, api_only=True)


if __name__ == "__main__":
    unittest.main()
