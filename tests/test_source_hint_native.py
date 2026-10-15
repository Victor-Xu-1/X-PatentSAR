"""Current source-token contracts through actual existing CPU OCR and writers."""

import copy
import unittest
from unittest.mock import patch

from test_hybrid_source_native import hybrid_page

from patent_sar_extractor.core import table_geometry
from patent_sar_extractor.core.activity_coordinates import extract_coordinate_tables
from patent_sar_extractor.core.activity_header_evidence import (
    serialize_header_evidence,
    validate_header_evidence,
)
from patent_sar_extractor.core.activity_header_proof import valid_header_proof
from patent_sar_extractor.core.activity_result_references import _observed


class SourceHintNativeTests(unittest.TestCase):
    def test_real_original_header_overrides_only_an_unqualified_layout_hint(self):
        original_reader = table_geometry.ocr_tokens_with_positions

        def weak_hint(page, **options):
            tokens = original_reader(page, **options)
            if options.get("dpi") == 200:
                tokens = copy.deepcopy(tokens)
                for token in tokens:
                    if "IC50" in token["text"]:
                        token.update(text="EC50 (uM)", confidence=0.2)
            return tokens

        doc, page = hybrid_page()
        with (
            doc,
            patch.object(
                table_geometry, "ocr_tokens_with_positions", side_effect=weak_hint
            ),
        ):
            result = extract_coordinate_tables(doc, [page.number])
        self.assertEqual(
            [row.cpd for row in result.rows], ["Compound 73", "Compound 58"]
        )
        self.assertEqual(
            [row.activity_values for row in result.rows],
            [{"IC50 (nM)": "12.4"}, {"IC50 (nM)": "9.1"}],
        )
        self.assertFalse(any(row.needs_review for row in result.rows))
        self.assertTrue(
            all(valid_header_proof(proof) for proof in result.header_observations)
        )
        records, catalog = serialize_header_evidence(
            result.rows, result.header_observations
        )
        self.assertEqual(
            validate_header_evidence({"rows": records, "header_observations": catalog}),
            [],
        )
        for record in records:
            for cell in record["activity_sources"][0]["cells"]:
                self.assertTrue(
                    _observed(cell, identifier=cell["field"] == "compound_id")
                )
        originals = [
            packet
            for proof in catalog.values()
            for packet in proof["original_source"]["columns"]
        ]
        self.assertTrue(
            any(
                packet["text"] == "EC50 (uM)" and packet["status"] == "unqualified"
                for packet in originals
            )
        )
