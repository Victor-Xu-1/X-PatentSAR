"""Only the owned Ketcher frame may compile WASM or be embedded by this origin."""

from __future__ import annotations

import unittest

from test_web_support import WebFixture


class StructureEditorSecurityTests(WebFixture, unittest.TestCase):
    def test_pdf_content_type_cannot_expand_correction_review_or_export_limits(self):
        with self.client() as client:
            for path, size in (
                ("/api/v1/projects/a/structures/a/correction", 1024 * 1024 + 1),
                ("/api/v1/projects/a/reviews/a", 65537),
                ("/api/v1/projects/a/export", 8 * 1024 * 1024 + 1),
            ):
                with self.subTest(path=path):
                    response = client.request(
                        "POST" if path.endswith("/export") else "PUT",
                        path,
                        content=b"x" * size,
                        headers={"Content-Type": "application/pdf"},
                    )
                    self.assertEqual(response.status_code, 413, response.text)

    def test_actual_pdf_upload_retains_its_streaming_upload_allowance(self):
        with self.client() as client:
            project = self.upload(client, self.pdf.read_bytes() + b" " * 70000)
            self.assertTrue(project["pdf"]["available"])
            self.assertEqual(project["pdf"]["page_count"], 1)

    def test_editor_frame_permissions_do_not_relax_the_workspace_or_api(self):
        frontend = self.root / "frontend"
        frontend.mkdir()
        (frontend / "index.html").write_text("<!doctype html><title>Workspace</title>")
        (frontend / "ketcher.html").write_text("<!doctype html><title>Editor</title>")
        (frontend / "assets").mkdir()
        (frontend / "assets/indigoWorker-controlled.js").write_text(
            "// Controlled worker response"
        )
        with self.client(frontend_dir=frontend) as client:
            editor = client.get("/ketcher.html")
            self.assertEqual(editor.status_code, 200)
            policy = editor.headers["content-security-policy"]
            self.assertIn("frame-ancestors 'self'", policy)
            self.assertIn("'wasm-unsafe-eval'", policy)
            self.assertIn("worker-src 'self' blob:", policy)
            self.assertNotIn("'unsafe-eval'", policy)
            policy = client.get("/assets/indigoWorker-controlled.js").headers[
                "content-security-policy"
            ]
            self.assertIn("'wasm-unsafe-eval'", policy)
            self.assertIn("frame-ancestors 'none'", policy)
            self.assertNotIn("'unsafe-eval'", policy)
            for path in ("/", "/api/v1/health"):
                policy = client.get(path).headers["content-security-policy"]
                self.assertIn("frame-ancestors 'none'", policy)
                self.assertNotIn("'wasm-unsafe-eval'", policy)
                self.assertNotIn("blob:", policy)

    def test_correction_body_limit_is_bounded_and_does_not_expand_other_writes(self):
        with self.client() as client:
            data = {
                "expected_revision": 0,
                "expected_source_fingerprint": "a" * 64,
                "fields": {
                    "display_id": "a",
                    "smiles": None,
                    "activities": [],
                    "structure_molfile": "x" * 70000,
                },
            }
            # Data is chemically invalid, but belongs within the bounded transport.
            response = client.put(
                "/api/v1/projects/a/structures/a/correction", json=data
            )
            self.assertEqual(response.status_code, 422, response.text)
            data["fields"]["structure_molfile"] = "x" * (1024 * 1024 + 1)
            self.assertEqual(
                client.put(
                    "/api/v1/projects/a/structures/a/correction", json=data
                ).status_code,
                413,
            )
            response = client.put(
                "/api/v1/projects/a/reviews/a",
                json={
                    "decision": "needs_review",
                    "note": "x" * 70000,
                    "expected_revision": 0,
                },
            )
            self.assertEqual(response.status_code, 413)
