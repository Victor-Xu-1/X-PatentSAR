"""A repeated condition must retain qualified observations on its actual page."""

import copy
import unittest
from unittest.mock import patch

import fitz

from patent_sar_extractor.core.activity_coordinates import extract_coordinate_tables
from patent_sar_extractor.core.activity_coverage import coverage_errors, coverage_packet
from patent_sar_extractor.core.source_geometry import SourceLayout, SourceTokens
from patent_sar_extractor.core.table_geometry import page_tokens
from tests.test_declared_table_continuations import draw_document


class ContinuationSourceBoundaryTests(unittest.TestCase):
    def test_plain_and_running_boundaries_also_need_the_same_original_packet(self):
        for prefix in ("", "WO2028/008765", "Table 71 (continued)"):
            with self.subTest(prefix=prefix), fitz.open() as document:
                draw_document(document, continued=prefix)
                parsed = extract_coordinate_tables(document, [0])
                self.assertEqual(
                    [row.cpd for row in parsed.rows], ["Compound 7", "Compound 19"]
                )
                packet = coverage_packet([0], parsed.coverage, parsed.rows)
                self.assertEqual(coverage_errors(packet, [0], rows=parsed.rows), [])
                target = next(
                    item
                    for item in packet["regions"]
                    if item.get("layout") and item["page_no"] == 2
                )
                self.assertIsInstance(
                    target["layout"].pop("continuation_context"), dict
                )
                self.assertTrue(coverage_errors(packet, [0], rows=parsed.rows))

    def test_declared_context_keeps_an_original_boundary_packet_and_refuses_removal(
        self,
    ):
        with fitz.open() as document:
            draw_document(document)
            parsed = extract_coordinate_tables(document, [0])
        packet = coverage_packet([0], parsed.coverage, parsed.rows)
        self.assertEqual(coverage_errors(packet, [0], rows=parsed.rows), [])
        current = next(
            item
            for item in packet["regions"]
            if item.get("layout") and item["page_no"] == 2
        )
        self.assertIsInstance(current["layout"].get("continuation_context"), dict)
        altered = copy.deepcopy(packet)
        target = next(
            item
            for item in altered["regions"]
            if item["region_id"] == current["region_id"]
        )
        target["layout"].pop("continuation_context")
        self.assertTrue(coverage_errors(altered, [0], rows=parsed.rows))

    def test_weak_current_condition_cannot_borrow_a_qualified_parent_header(self):
        eligible = []

        def source(page):
            observed = page_tokens(page)
            if page.number == 0:
                return observed
            bounds = tuple(page.rect)
            tokens = [
                {
                    **token,
                    "source": "raster",
                    "confidence": 0.2
                    if token["text"] == "24" and token["y"] < 100
                    else 1.0,
                }
                for token in observed
            ]
            self.assertTrue(any(token["confidence"] == 0.2 for token in tokens))
            return SourceTokens(tokens, SourceLayout((), bounds), bounds)

        def record_eligibility(_page, page_no, _tokens, _region, _schema, **_kwargs):
            eligible.append(page_no)
            return []

        # This isolates header eligibility, not OCR/measurement accuracy. The
        # previous test exercises the actual generated-native producer/reader.
        with fitz.open() as document:
            draw_document(document)
            with (
                patch(
                    "patent_sar_extractor.core.activity_coordinates.page_tokens",
                    side_effect=source,
                ),
                patch(
                    "patent_sar_extractor.core.activity_coordinates.parse_grid",
                    side_effect=record_eligibility,
                ),
            ):
                extract_coordinate_tables(document, [0])
        self.assertEqual(eligible, [1])
