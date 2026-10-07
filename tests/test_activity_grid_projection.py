"""Real native-grid observations through isolated schema-v1 API consumers."""

from __future__ import annotations

import hashlib
import json
import unittest
from dataclasses import asdict

import fitz

from patent_sar_extractor.core.activity_coordinates import extract_coordinate_tables
from patent_sar_extractor.web.service import import_run
from tests.test_activity_parser_modules import draw_grid
from tests.test_web_support import WebFixture, artifact_run


class ActivityGridProjectionTests(WebFixture, unittest.TestCase):
    def test_duplicate_and_unknown_grid_fields_keep_values_units_and_exact_focus(self):
        pdf = self.root / "native-grid.pdf"
        headers = ["No.", "MET IC50 (nM)", "MET IC50 (nM)", "Unknown signal (pM)"]
        with fitz.open() as doc:
            page = doc.new_page(width=700, height=400)
            draw_grid(
                page,
                [headers, ["31A", "<2", "<2", "ND"]],
                caption="Table 83. Target: MET; Assay: binding",
            )
            extracted = extract_coordinate_tables(doc, [0]).rows
            doc.save(pdf)
        self.assertEqual(len(extracted), 1)
        self.assertTrue(extracted[0].needs_review)
        run = artifact_run(self.root / "fixture", pdf, accepted=False, rows=1)
        activity_path = run / "activity/activity_data.json"
        payload = json.loads(activity_path.read_text())
        payload["rows"] = [asdict(extracted[0])]
        payload["active_cpds"] = [extracted[0].cpd]
        activity_path.write_text(json.dumps(payload))
        original_sha = hashlib.sha256(activity_path.read_bytes()).hexdigest()
        project = import_run(self.state, run, pdf_path=pdf)
        prefix = f"/api/v1/projects/{project.id}"
        cells = extracted[0].activity_sources[0]["cells"][1:]
        with self.client() as client:
            response = client.get(prefix + "/results")
            self.assertEqual(response.status_code, 200, response.text)
            row = next(r for r in response.json()["items"] if r["id"] == "Compound 31A")
            self.assertEqual(
                [a["value"] for a in row["activities"]], ["<2", "<2", "ND"]
            )
            self.assertEqual([a["unit"] for a in row["activities"]], ["nM", "nM", "pM"])
            self.assertTrue(
                all(
                    a["target"] == "MET" and a["assay"] == "binding"
                    for a in row["activities"]
                )
            )
            self.assertEqual(len(response.json()["activity_columns"]), 3)
            self.assertEqual(len(set(row["activity_source_keys"])), 3)
            for index, key in enumerate(row["activity_source_keys"]):
                focused = client.get(
                    prefix + "/pages/1",
                    params={"focus_compound": row["id"], "focus_activity": key},
                )
                self.assertEqual(focused.status_code, 200, focused.text)
                self.assertEqual(focused.json()["activity_focus"]["status"], "located")
                boxes = focused.json()["activity_focus"]["boxes"]
                self.assertEqual(len(boxes), 1)
                # The PDF transform uses float32 points; identity/ownership must
                # be exact while its serialized coordinates retain that precision.
                for actual, expected in zip(
                    boxes[0], cells[index]["bbox"], strict=True
                ):
                    self.assertAlmostEqual(actual, expected, places=5)
            exported = client.post(
                prefix + "/export", json={"format": "json", "compound_ids": []}
            )
            self.assertEqual(exported.status_code, 200, exported.text)
            exported_row = next(
                r for r in exported.json()["items"] if r["id"] == row["id"]
            )
            self.assertEqual(exported_row["activities"], row["activities"])
        self.assertEqual(
            hashlib.sha256(activity_path.read_bytes()).hexdigest(), original_sha
        )


if __name__ == "__main__":
    unittest.main()
