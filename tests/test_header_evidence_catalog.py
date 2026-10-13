"""Shared header storage, rejected source retention and downstream references."""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz
from test_activity_parser_modules import draw_grid

from patent_sar_extractor.core.activity_artifacts import save_results
from patent_sar_extractor.core.activity_coordinates import extract_coordinate_tables
from patent_sar_extractor.core.activity_header_evidence import (
    proof_id,
    serialize_header_evidence,
    validate_header_evidence,
)
from patent_sar_extractor.core.activity_models import ActivityRow
from patent_sar_extractor.web.activity_provenance import source_evidence


class HeaderEvidenceCatalogTests(unittest.TestCase):
    def test_shared_proof_is_hashed_once_per_write_or_validation(self):
        rows, proof = self.rows()
        with patch(
            "patent_sar_extractor.core.activity_header_evidence.proof_id",
            wraps=proof_id,
        ) as digest:
            records, catalog = serialize_header_evidence(rows, [proof])
            self.assertEqual(digest.call_count, 1)
        with patch(
            "patent_sar_extractor.core.activity_header_evidence.proof_id",
            wraps=proof_id,
        ) as digest:
            validate_header_evidence({"rows": records, "header_observations": catalog})
            self.assertEqual(digest.call_count, 1)

    def rows(self, status="observed_header_consensus", count=80):
        proof = {
            "status": status,
            "page_no": 1,
            "header_band_bbox": [60, 100, 330, 125],
            "observations": [
                {"method": "header_ocr_400dpi", "text": "IC50 (nM) " * 500}
            ],
        }
        source = {
            "page_no": 1,
            "table_id": "Table 7",
            "header_resolution": proof,
            "header_region": {"page_no": 1, "bbox": [60, 100, 330, 125]},
            "cells": [
                {"field": "IC50 (nM)", "value": "17", "bbox": [195, 125, 330, 150]}
            ],
        }
        return [
            ActivityRow(
                cpd=f"Compound {i + 1}",
                activity_values={"IC50 (nM)": "17"},
                activity_sources=[source],
            )
            for i in range(count)
        ], proof

    def test_full_observation_stored_once_without_mutating_source(self):
        rows, proof = self.rows()
        original = copy.deepcopy(proof)
        records, catalog = serialize_header_evidence(rows, [proof, proof])
        self.assertEqual(len(catalog), 1)
        self.assertEqual(proof, original)
        self.assertIs(rows[0].activity_sources[0]["header_resolution"], proof)
        encoded = json.dumps({"rows": records, "header_observations": catalog})
        self.assertEqual(encoded.count("header_ocr_400dpi"), 1)
        self.assertLess(len(encoded), len(json.dumps(proof)) * 10)
        self.assertEqual(
            validate_header_evidence({"rows": records, "header_observations": catalog}),
            [],
        )
        self.assertEqual(
            source_evidence(records[0], (1, None, None))[0].cells[0].value, "17"
        )

    def test_missing_changed_or_unhashable_reference_is_rejected(self):
        rows, proof = self.rows(count=1)
        records, catalog = serialize_header_evidence(rows, [proof])
        for field, value in (
            ("evidence_ref", "0" * 64),
            ("status", "resolved"),
            ("evidence_ref", {}),
        ):
            changed = copy.deepcopy(records)
            changed[0]["activity_sources"][0]["header_resolution"][field] = value
            with (
                self.subTest(field=field, value=value),
                self.assertRaises((ValueError, TypeError)),
            ):
                validate_header_evidence(
                    {"rows": changed, "header_observations": catalog}
                )
        changed = copy.deepcopy(catalog)
        next(iter(changed.values()))["observations"][0]["text"] = "other unit"
        with self.assertRaises(ValueError):
            validate_header_evidence({"rows": records, "header_observations": changed})

    def test_unresolved_proof_cannot_hide_by_clearing_row_review(self):
        rows, proof = self.rows("unresolved", count=1)
        records, catalog = serialize_header_evidence(rows, [proof])
        self.assertFalse(records[0]["needs_review"])
        self.assertTrue(
            validate_header_evidence({"rows": records, "header_observations": catalog})
        )

    def test_rejected_no_row_observation_survives_production_adapter_and_writer(self):
        with fitz.open() as doc:
            page = doc.new_page()
            draw_grid(page, [["No.", "Noise"], ["42", "17"]])
            supplied = []

            def reject(page, region, original, *, tokens, evidence_sink):
                supplied.extend(tokens)
                evidence_sink.append(
                    {"status": "unresolved", "observations": [{"text": "unreadable"}]}
                )

            with patch(
                "patent_sar_extractor.core.activity_coordinates.refine_scanned_header",
                side_effect=reject,
            ):
                parsed = extract_coordinate_tables(doc, [0])
        self.assertTrue(supplied)
        self.assertEqual(parsed.rows, [])
        self.assertEqual(len(parsed.header_observations), 1)
        self.assertEqual(parsed.header_observations[0]["page_no"], 1)
        self.assertEqual(len(parsed.header_observations[0]["table_bbox"]), 4)
        with tempfile.TemporaryDirectory() as root:
            save_results(
                [],
                Path(root),
                {},
                coverage={},
                header_observations=parsed.header_observations,
            )
            payload = json.loads((Path(root) / "activity_data.json").read_text())
        self.assertEqual(payload["rows"], [])
        self.assertIn("unreadable", str(payload["header_observations"]))
