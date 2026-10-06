"""Identity-only worker execution with real PDF/metadata IO, no scientific model."""

from __future__ import annotations

import argparse
import ast
import json
import logging
import os
import re
import unittest
from pathlib import Path
from types import CodeType, FunctionType
from unittest.mock import Mock, patch

import fitz
import numpy as np
from test_web_support import WebFixture

from patent_sar_extractor.artifact_io import write_json_atomic
from patent_sar_extractor.contracts import (
    STRUCTURES_SCHEMA,
    STRUCTURES_SCHEMA_VERSION,
    artifact_identity,
)


class StructureWorkerIdentityTests(WebFixture, unittest.TestCase):
    def worker(self):
        path = (
            Path(__file__).resolve().parents[1]
            / "src/patent_sar_extractor/workers/extract_structures.py"
        )
        source = ast.parse(path.read_text())
        definitions = [
            node
            for node in source.body
            if isinstance(node, ast.FunctionDef)
            and node.name
            in {"_load_crop_regions", "extract_structures_from_pdf", "main"}
        ]
        namespace = {
            "argparse": argparse,
            "fitz": fitz,
            "json": json,
            "os": os,
            "re": re,
            "Path": Path,
            "logger": logging.getLogger(__name__),
            "DECIMER_AVAILABLE": True,
            "get_model": Mock(),
            "write_json_atomic": write_json_atomic,
            "artifact_identity": artifact_identity,
            "STRUCTURES_SCHEMA": STRUCTURES_SCHEMA,
            "STRUCTURES_SCHEMA_VERSION": STRUCTURES_SCHEMA_VERSION,
            "np": np,
        }
        # Execute the actual function/parser definitions, isolating only eager
        # vendor imports. No model, page segmentation or science acceptance.
        self.assertEqual(
            {node.name for node in definitions},
            {"_load_crop_regions", "extract_structures_from_pdf", "main"},
        )
        for node in definitions:
            module = compile(
                ast.Module(body=[node], type_ignores=[]), str(path), "exec"
            )
            code = next(
                value
                for value in module.co_consts
                if isinstance(value, CodeType) and value.co_name == node.name
            )
            defaults = tuple(ast.literal_eval(value) for value in node.args.defaults)
            namespace[node.name] = FunctionType(code, namespace, node.name, defaults)
        return namespace

    def metadata(self, options, expected):
        worker = self.worker()
        output = self.root / "worker-output"
        with (
            patch.dict(os.environ, {"DECIMER_SEGMENTATION_MODEL_DIR": ""}),
            patch("patent_sar_extractor.resource_admission.wait_for_memory"),
        ):
            result = worker["extract_structures_from_pdf"](
                str(self.pdf), [], str(output), **options
            )
        self.assertEqual(result["patent_number"], expected)
        self.assertEqual(
            json.loads((output / "metadata.json").read_text())["patent_number"],
            expected,
        )
        self.assertEqual(result["total_structures"], 0)
        worker["get_model"].assert_called_once_with()

    def test_explicit_unknown_is_not_replaced_in_serialized_metadata(self):
        self.metadata({"patent_id": ""}, "")

    def test_omitted_worker_identity_preserves_standalone_inference(self):
        self.metadata({}, "input")

    def test_explicit_identity_remains_exact_in_worker_metadata(self):
        self.metadata({"patent_id": "LOCAL-IDENTITY"}, "LOCAL-IDENTITY")

    def test_worker_parser_distinguishes_omitted_from_explicit_unknown(self):
        worker = self.worker()
        worker["extract_structures_from_pdf"] = Mock()
        for options, expected in (
            ([], None),
            (["--patent-id", ""], ""),
            (["--patent-id", "LOCAL-IDENTITY"], "LOCAL-IDENTITY"),
        ):
            with patch(
                "sys.argv",
                [
                    "worker",
                    "--pdf",
                    str(self.pdf),
                    "--output",
                    str(self.root / "out"),
                    "--pages",
                    "0",
                    *options,
                ],
            ):
                worker["main"]()
            self.assertEqual(
                worker["extract_structures_from_pdf"].call_args.kwargs["patent_id"],
                expected,
            )

    def test_crop_save_failure_never_registers_a_page_as_a_structure(self):
        worker = self.worker()
        worker["_resolve_crop_pixels"] = lambda crop, page, dpi, w, h: (0, 0, w, h)
        worker["segment_chemical_structures"] = Mock(
            return_value=(
                [np.zeros((50, 80, 3), dtype=np.uint8)],
                [(10, 10, 60, 90)],
            )
        )
        output = self.root / "crop-failure"
        with (
            patch.dict(os.environ, {"DECIMER_SEGMENTATION_MODEL_DIR": ""}),
            patch("patent_sar_extractor.resource_admission.wait_for_memory"),
            patch("PIL.Image.Image.save", side_effect=OSError("Controlled crop fault")),
            self.assertRaisesRegex(RuntimeError, "segmentation failed"),
        ):
            worker["extract_structures_from_pdf"](str(self.pdf), [0], str(output))
        metadata = json.loads((output / "metadata.json").read_text())
        self.assertEqual(metadata["structures"], [])
        self.assertEqual(metadata["total_structures"], 0)
        self.assertEqual(len(metadata["failed_pages"]), 1)
        self.assertTrue((output / "page_001.png").is_file())
