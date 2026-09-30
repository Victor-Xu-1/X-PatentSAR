"""Opt-in real models and original-patent evidence; never uses production state.

The operator selects the external run/PDF and configured CPU environments.
These tests prove review inference, not OCSR accuracy or formal ADMET validation.
"""

from __future__ import annotations

import hashlib
import math
import os
import time
import unittest
from pathlib import Path
from urllib.parse import quote

from test_web_analysis_api import AnalysisFixture

from patent_sar_extractor.web.analysis_runtime import AnalysisSettings


@unittest.skipUnless(
    os.environ.get("PATENTSAR_ANALYSIS_REAL_TESTS") == "1",
    "Explicit external model/PDF integration inputs required",
)
class RealAnalysisTests(AnalysisFixture, unittest.TestCase):
    # Reuse only the authenticated-app fixture, not the parent's mock test suite.
    def test_real_history_crop_to_rdkit_to_admet_api_and_immutable_evidence(self):
        self.settings = AnalysisSettings.from_environment()
        run = Path(os.environ["PATENTSAR_ANALYSIS_REAL_RUN"])
        pdf = Path(os.environ["PATENTSAR_ANALYSIS_REAL_PDF"])
        self.assertEqual(
            hashlib.sha256(pdf.read_bytes()).hexdigest(),
            os.environ["PATENTSAR_ANALYSIS_REAL_PDF_SHA256"],
        )
        originals = {
            p: hashlib.sha256(p.read_bytes()).hexdigest() for p in run.glob("*/*.json")
        }
        crop = run / "structures/.chunks/chunk_000/structure_0000.png"
        self.assertEqual(
            hashlib.sha256(crop.read_bytes()).hexdigest(),
            "fb853644b526bce3445c9a1b6594866d86c14e8737e89207843347b5881fdbdb",
        )
        with self.client() as client:
            workspace = self.analysis.workspace
            project = workspace.import_run(run, pdf_path=pdf)
            self.assertEqual(project.acceptance.state, "historical")
            self.assertEqual(project.pdf.page_count, 1553)
            self.assertEqual(
                sum(bool(c.smiles) for c in workspace.compounds(project.id)), 0
            )
            self.assertTrue(self.analysis.capabilities()["admet"])
            prefix = f"/api/v1/projects/{project.id}"
            page = client.get(prefix + "/pages/361/image?scale=0.5")
            self.assertEqual(page.status_code, 200)
            self.assertTrue(page.content.startswith(b"\x89PNG"))
            compound_id = workspace.compounds(project.id)[0].id
            started = time.monotonic()
            recognized = client.post(
                prefix + f"/compounds/{quote(compound_id, safe='')}/recognize", json={}
            )
            self.assertEqual(recognized.status_code, 200, recognized.text)
            recognition = recognized.json()
            self.assertEqual(recognition["status"], "recognized")
            self.assertTrue(recognition["review_only"])
            self.assertEqual(
                recognition["engine"], {"name": "DECIMER", "version": "2.8.0"}
            )
            self.assertLess(time.monotonic() - started, 180)
            from rdkit import Chem
            from rdkit.Chem import rdMolDescriptors

            molecule = Chem.MolFromSmiles(recognition["smiles"])
            self.assertEqual(rdMolDescriptors.CalcMolFormula(molecule), "C57H72F2N12O6")
            started = time.monotonic()
            predicted = client.post(
                "/api/v1/analysis/admet", json={"smiles": [recognition["smiles"]]}
            )
            self.assertEqual(predicted.status_code, 200, predicted.text)
            prediction = predicted.json()
            self.assertTrue(prediction["review_only"])
            self.assertEqual(prediction["engine"]["version"], "2.0.1")
            properties = prediction["predictions"][0]["properties"]
            self.assertEqual(len(properties), 52)
            self.assertEqual(sum(p["kind"] == "descriptor" for p in properties), 11)
            self.assertEqual(sum(p["kind"] == "prediction" for p in properties), 41)
            self.assertTrue(all(math.isfinite(p["value"]) for p in properties))
            self.assertLess(time.monotonic() - started, 180)
            self.assertEqual(
                client.post(
                    "/api/v1/analysis/admet", json={"smiles": ["not-SMILES"]}
                ).status_code,
                422,
            )
            summary = client.get(prefix + "/evidence-summary").json()
            self.assertEqual(summary["counts"]["structures"], 1189)
            self.assertEqual(summary["counts"]["activity_rows"], 1157)
            self.assertEqual(summary["counts"]["compounds"], 1156)
            self.assertEqual(summary["counts"]["smiles"], 0)
            self.assertIn(361, summary["source_pages"])
            self.assertEqual(summary["acceptance"]["state"], "historical")
            self.assertTrue(
                all(c.smiles is None for c in workspace.compounds(project.id))
            )
            self.assertEqual(
                client.post(
                    "/api/v1/analysis/admet", json={"smiles": [recognition["smiles"]]}
                ).json(),
                prediction,
            )
            self.assertEqual(
                client.post(
                    prefix + f"/compounds/{quote(compound_id, safe='')}/recognize",
                    json={},
                ).json(),
                recognition,
            )
            self.assertFalse(list(self.analysis.cache.root.glob("worker-*")))
        self.assertEqual(
            originals,
            {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in originals},
        )
