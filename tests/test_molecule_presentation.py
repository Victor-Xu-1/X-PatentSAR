"""Real RDKit PNG rendering and independent manual-review counters."""

from __future__ import annotations

import hashlib
import unittest

from patent_sar_extractor.web.errors import WebError
from patent_sar_extractor.web.molecule_drawing import draw_smiles
from patent_sar_extractor.web.service import import_run
from test_web_support import WebFixture, artifact_run


class MoleculePresentationTests(WebFixture, unittest.TestCase):
    def test_real_derived_png_is_available_without_modifying_source_artifacts(self):
        run = artifact_run(self.root / "redraw", self.pdf)
        before = {
            path: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in run.rglob("*")
            if path.is_file()
        }
        project = import_run(self.state, run, pdf_path=self.pdf)
        with self.client() as client:
            prefix = f"/api/v1/projects/{project.id}"
            row = client.get(prefix + "/results").json()["items"][0]
            response = client.get(row["redraw_image_url"])
            self.assertEqual(
                response.status_code,
                200,
                response.text if response.status_code != 200 else "",
            )
            self.assertEqual(response.headers["content-type"], "image/png")
            self.assertTrue(response.content.startswith(b"\x89PNG\r\n\x1a\n"))
            original = client.get(row["structure_image_url"])
            self.assertEqual(original.status_code, 200)
            self.assertNotEqual(original.content, response.content)
        self.assertEqual(
            before,
            {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in before},
        )

    def test_invalid_and_oversized_derived_molecules_are_explicit_errors(self):
        for value in ("", "C1CC", "C" * 4097, "C" * 513):
            with self.subTest(value=value[:20]), self.assertRaises(WebError):
                draw_smiles(value)

    def test_manual_review_is_counted_separately_from_binding_and_formal_qa(self):
        project = import_run(
            self.state,
            artifact_run(self.root / "review-counts", self.pdf),
            pdf_path=self.pdf,
        )
        with self.client() as client:
            prefix = f"/api/v1/projects/{project.id}"
            initial = client.get(prefix).json()
            self.assertEqual(initial["summary"]["manually_reviewed"], 0)
            self.assertEqual(initial["summary"]["manual_review_pending"], 2)
            client.put(
                prefix + "/reviews/Compound%201",
                json={
                    "decision": "needs_review",
                    "note": "Check drawing",
                    "expected_revision": 0,
                },
            ).raise_for_status()
            self.assertEqual(
                client.get(prefix).json()["summary"]["manually_reviewed"], 0
            )
            client.put(
                prefix + "/reviews/Compound%201",
                json={
                    "decision": "approved",
                    "note": "Checked original",
                    "expected_revision": 1,
                },
            ).raise_for_status()
            final = client.get(prefix).json()
            self.assertEqual(final["summary"]["manually_reviewed"], 1)
            self.assertEqual(final["summary"]["manual_review_pending"], 1)
            self.assertEqual(initial["acceptance"], final["acceptance"])
            self.assertEqual(
                initial["summary"]["confirmed"], final["summary"]["confirmed"]
            )
