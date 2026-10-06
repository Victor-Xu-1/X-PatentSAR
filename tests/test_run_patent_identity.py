"""Explicit unknown task identity differs from omitted standalone CLI identity."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from test_web_support import WebFixture

from patent_sar_extractor.application.pipeline import execute_pipeline
from patent_sar_extractor.application.progress import PipelineProgress
from patent_sar_extractor.cli import build_parser


class IdentityCaptured(Exception):
    pass


class RunPatentIdentityTests(WebFixture, unittest.TestCase):
    def assert_identity(self, filename, options, expected):
        args = build_parser().parse_args(
            [
                "run",
                "--pdf",
                str(self.root / filename),
                "--output",
                str(self.root / "output"),
                *options,
            ]
        )

        def capture(state):
            self.assertEqual(state.patent_id, expected)
            self.assertEqual(state.pipeline_log["patent_id"], expected)
            raise IdentityCaptured()

        with (
            patch(
                "patent_sar_extractor.application.pipeline.execute_classify",
                side_effect=capture,
            ),
            self.assertRaises(IdentityCaptured),
        ):
            execute_pipeline(args, PipelineProgress())

    def test_explicit_empty_preserves_unknown_identity(self):
        self.assert_identity("WO1234567.pdf", ["--patent-id", ""], "")

    def test_omitted_identity_keeps_standalone_filename_inference(self):
        self.assert_identity("WO1234567.pdf", [], "WO1234567")
        self.assert_identity("controlled-input.pdf", [], "controlled-input")

    def test_explicit_identity_is_not_replaced_by_filename(self):
        self.assert_identity(
            "WO1234567.pdf", ["--patent-id", "LOCAL-IDENTITY"], "LOCAL-IDENTITY"
        )

    def test_empty_identity_requires_explicit_output_not_shared_root(self):
        args = build_parser().parse_args(
            ["run", "--pdf", str(self.pdf), "--patent-id", ""]
        )
        with (
            patch(
                "patent_sar_extractor.application.pipeline.state_dir",
                return_value=self.root / "isolated-state",
            ),
            patch(
                "patent_sar_extractor.application.pipeline.execute_classify",
                side_effect=AssertionError("Guard must stop before any worker"),
            ),
            self.assertRaisesRegex(ValueError, "explicit output"),
        ):
            execute_pipeline(args, PipelineProgress())
