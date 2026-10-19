"""The shared fragment policy survives source capture and real raster columns."""

import copy
import json
import unittest
from unittest.mock import Mock, patch

import fitz

from patent_sar_extractor.core.activity_header_columns import observe_header_columns
from patent_sar_extractor.core.activity_header_identity import compact_header
from patent_sar_extractor.core.activity_header_observation import refine_scanned_header
from patent_sar_extractor.core.activity_header_pair import observe_header_pair
from patent_sar_extractor.core.activity_header_proof import (
    valid_header_column,
    valid_header_proof,
)
from patent_sar_extractor.core.activity_headers import context_from_text, grid_schema
from patent_sar_extractor.core.page_ocr_cache import get_ocr_engine
from tests.header_support import observed_headers
from tests.test_source_hint_authority import source_tokens, token


class HeaderFragmentSourceTests(unittest.TestCase):
    def test_complete_source_proof_keeps_qualified_target_and_unit_but_not_weak_prefix(
        self,
    ):
        region = {"xs": [40, 90, 240], "ys": [100, 140, 170]}
        old, fresh = "UnknownAssay\nTargetX\nEC50 nM", "AssayA TargetX EC50 (nM)"
        parts = [
            token("No.", 0.99, 65, 120),
            token("UnknownAssay", 0.2, 150, 105),
            token("TargetX", 0.99, 150, 116),
            token("EC50 nM", 0.99, 150, 130),
        ]
        original = grid_schema(
            context_from_text("Table 7. Binding assay"), [["No.", old]]
        )
        page = Mock(rect=fitz.Rect(0, 0, 500, 600))
        page.get_text.return_value = []
        with (
            patch(
                "patent_sar_extractor.core.activity_header_observation.ocr_tokens_with_positions",
                return_value=[],
            ),
            patch(
                "patent_sar_extractor.core.activity_header_observation._prefix",
                return_value="Table 7. Binding assay",
            ),
            patch(
                "patent_sar_extractor.core.activity_header_observation.observe_header_columns",
                side_effect=lambda page, region, limit, dpi, tokens: observed_headers(
                    [["No.", fresh]], region, limit, dpi
                ),
            ),
        ):
            result = refine_scanned_header(
                page, region, original, tokens=source_tokens(parts)
            )
        proof = json.loads(json.dumps(result.header_resolution))
        self.assertEqual(proof["status"], "observed_header_consensus")
        self.assertTrue(valid_header_proof(proof))
        self.assertEqual(proof["original_headers"][1], old)
        changed = copy.deepcopy(proof)
        observed = changed["original_source"]["columns"][1]
        observed["tokens"][0]["confidence"] = 0.99
        observed["status"] = "qualified"
        self.assertFalse(valid_header_proof(changed))

    def test_real_raster_cell_retains_weak_detector_and_full_physical_header(self):
        with fitz.open() as original:
            page = original.new_page(width=300, height=220)
            for index, text in enumerate(("AssayA", "TargetX", "EC50 (nM)")):
                page.insert_text((100, 95 + index * 14), text, fontsize=9)
            page.insert_text((45, 95), "No.", fontsize=9)
            pixels = page.get_pixmap(matrix=fitz.Matrix(4, 4), alpha=False).tobytes(
                "png"
            )
        with fitz.open() as document:
            page = document.new_page(width=300, height=220)
            page.insert_image(page.rect, stream=pixels)
            region = {"xs": [30, 85, 210], "ys": [75, 135, 155]}
            base = get_ocr_engine()[1]
            weak = []

            def partial(image, *, use_det, use_cls):
                result, timing = base(image, use_det=use_det, use_cls=use_cls)
                if use_det:
                    result = copy.deepcopy(result)
                    for part in result:
                        if part[1] == "AssayA":
                            part[2] = 0.3
                            weak.append(True)
                return result, timing

            with (
                patch(
                    "patent_sar_extractor.core.activity_header_columns.get_ocr_engine",
                    return_value=("rapidocr", partial),
                ),
                patch(
                    "patent_sar_extractor.core.activity_header_pair.get_auxiliary_text_runtime",
                    side_effect=AssertionError(
                        "Complete primary must not load a model to vote"
                    ),
                ),
            ):
                pair = observe_header_pair(page, region, 1, (), observe_header_columns)
            self.assertEqual(len(weak), 2)
            for view, dpi in zip(pair, (400, 600)):
                column = json.loads(json.dumps(view.columns[1]))
                # Header identity already uses case/whitespace comparison.
                # Keep the actual SDK casing in raw_text and its proof; this
                # test is not a new exact-character OCR accuracy benchmark.
                self.assertEqual(
                    compact_header(column["raw_text"]),
                    compact_header("AssayA\nTargetX\nEC50 (nM)"),
                )
                self.assertTrue(view.verified[1])
                self.assertEqual(column["detection_parts"][0]["confidence"], 0.3)
                self.assertTrue(
                    valid_header_column(
                        column, 1, column["raw_text"], [30, 75, 210, 135], dpi
                    )
                )
