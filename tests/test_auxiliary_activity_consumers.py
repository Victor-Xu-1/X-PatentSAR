"""Shared admission/serialization controls; no private PDF or model claim."""

import copy
import json
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path

from patent_sar_extractor.artifact_catalog import expand_shared_json, pack_shared_json
from patent_sar_extractor.core.activity_header_evidence import (
    proof_id,
    validate_header_evidence,
)
from patent_sar_extractor.core.activity_header_proof import valid_header_proof
from patent_sar_extractor.core.activity_join import activity_evidence_errors
from patent_sar_extractor.core.qa_report import build_qa_report
from patent_sar_extractor.core.table_cells import observe_original_cell
from patent_sar_extractor.core.text_ocr.cell_capture import refine_text_pair
from patent_sar_extractor.web.acceptance import authority
from patent_sar_extractor.workers.gen_final_results import export_validation
from tests import test_auxiliary_cell_evidence as cell_fixture
from tests.test_source_led_export import run_fixture, save
from tests.test_web_acceptance import complete_payloads


class AuxiliaryActivityConsumerTests(unittest.TestCase):
    def setUp(self):
        fixture = cell_fixture.AuxiliaryCellEvidenceTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        fixture.page.insert_text((3, 45), "No.", fontsize=4)
        headers = [["No.", "HTRF\nEC50"]]
        region = {"xs": [0, 15, 140], "ys": [25, 80, 100]}
        columns = []
        primaries = [
            {
                **p,
                "native_text": "",
                "physical_column": 1,
                "crosses_boundary": False,
                "detector_conflict": False,
            }
            for p in fixture.primaries
        ]
        pair = refine_text_pair(
            fixture.images, primaries, cell_fixture.ControlledAuxiliary()
        )
        self.assertIsNotNone(pair)
        for dpi, reading in zip((400, 600), pair):
            bounds = [0, 25, 15, 80]

            def identity_text(image, *, use_det, use_cls):
                return ([], None) if use_det else ([["No.", 0.99]], None)

            identity = {
                **observe_original_cell(
                    fixture.page,
                    bounds,
                    "header",
                    dpi,
                    identity_text,
                    lambda text, _kind: text,
                ).evidence(dpi, bounds),
                "physical_column": 0,
                "native_text": "",
                "crosses_boundary": False,
                "detector_conflict": False,
            }
            columns.append(
                {
                    "method": f"header_ocr_{dpi}dpi",
                    "prefix": "Table 3. Binding assay",
                    "matrix": headers,
                    "columns": [identity, reading],
                }
            )
        self.proof = {
            "column_contract": 1,
            "status": "observed_header_consensus",
            "page_no": 1,
            "header_band_bbox": [0, 25, 140, 80],
            "observations": columns,
            "original_headers": [],
            "original_context": "",
            "conflicting_columns": [],
            "unverified_columns": [],
            "context_conflict": False,
        }
        self.assertTrue(valid_header_proof(self.proof))
        self.catalog = {proof_id(self.proof): self.proof}

    def test_lossless_shared_storage_replays_current_physical_and_model_proof(self):
        payload = {"header_observations": self.catalog, "rows": []}
        restored = expand_shared_json(json.loads(json.dumps(pack_shared_json(payload))))
        self.assertEqual(restored, payload)
        self.assertEqual(validate_header_evidence(restored), [])
        tampered = copy.deepcopy(restored)
        proof = next(iter(tampered["header_observations"].values()))
        del proof["observations"][0]["columns"][1]["auxiliary_text"]
        tampered["header_observations"] = {proof_id(proof): proof}
        with self.assertRaisesRegex(ValueError, "Unproved"):
            validate_header_evidence(tampered)

    def test_web_and_core_require_actual_original_even_with_saved_success(self):
        payloads = complete_payloads()
        payloads["activity"]["header_observations"] = self.catalog
        errors = activity_evidence_errors(payloads["activity"])
        self.assertTrue(any("Original PDF is required" in e for e in errors))
        decision, _ = authority(payloads, pdf_verified=True, marker=None)
        self.assertEqual(decision.state, "failed")
        decision, _ = authority(
            payloads,
            pdf_verified=True,
            marker=None,
            open_original=lambda: nullcontext(self.fixture.document),
        )
        self.assertEqual(decision.state, "accepted", decision.errors)
        # Only the ordinary primary ID column changes; the paired auxiliary
        # measurement crop and all saved success flags remain identical.
        self.fixture.page.insert_text((3, 60), "X", fontsize=3)
        decision, _ = authority(
            payloads,
            pdf_verified=True,
            marker=None,
            open_original=lambda: nullcontext(self.fixture.document),
        )
        self.assertEqual(decision.state, "failed")
        self.assertIn("original page pixels", " ".join(decision.errors))

    def test_export_and_deterministic_qa_cannot_omit_original_replay(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_fixture(root)
            activity_path = root / "activity/activity_data.json"
            payload = json.loads(activity_path.read_text())
            payload["header_observations"] = self.catalog
            save(activity_path, payload)
            _, _, errors = export_validation(
                str(root / "structure_bindings/bindings.json"),
                str(root / "smiles/smiles_results.json"),
                str(activity_path),
            )
            self.assertTrue(any("Original PDF is required" in e for e in errors))
            qa = build_qa_report(str(root))
            self.assertTrue(
                any(
                    "Original PDF is required" in e
                    for e in qa["acceptance"]["hard_errors"]
                )
            )
            wrong = str(root / "original.pdf")
            _, _, errors = export_validation(
                str(root / "structure_bindings/bindings.json"),
                str(root / "smiles/smiles_results.json"),
                str(activity_path),
                original_pdf=wrong,
            )
            self.assertTrue(any("original page pixels" in e for e in errors))
