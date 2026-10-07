from __future__ import annotations

import hashlib
import io
import json
import unittest

from PIL import Image
from test_web_support import WebFixture, artifact_run, make_pdf

from patent_sar_extractor.web.errors import WebError
from patent_sar_extractor.web.service import WorkspaceService, import_run


class PDFTests(WebFixture, unittest.TestCase):
    def test_real_upload_text_and_png(self):
        with self.client() as client:
            project = self.upload(client)
            self.assertEqual(
                project["pdf"]["sha256"],
                hashlib.sha256(self.pdf.read_bytes()).hexdigest(),
            )
            self.assertEqual(project["acceptance"]["state"], "not_run")
            prefix = f"/api/v1/projects/{project['id']}/pages"
            page = client.get(prefix + "/1").json()
            self.assertIn("Controlled local PDF evidence", page["text"])
            self.assertEqual(page["source_mode"], "native")
            self.assertEqual((page["width"], page["height"]), (300, 200))
            png = client.get(prefix + "/1/image?scale=1.5")
            self.assertEqual(png.headers["content-type"], "image/png")
            with Image.open(io.BytesIO(png.content)) as image:
                self.assertEqual(image.size, (450, 300))
                self.assertEqual(image.getpixel((100, 100)), (255, 0, 0))
            for path in ("/0", "/2", "/1/image?scale=nan", "/1/image?scale=10"):
                self.assertIn(client.get(prefix + path).status_code, (404, 422))

    def test_invalid_encrypted_empty_uploads_and_path_names(self):
        encrypted = make_pdf(self.root / "encrypted.pdf", encrypted=True)
        with self.client() as client:
            for data in (b"not a PDF", b"", encrypted.read_bytes()):
                response = client.post(
                    "/api/v1/projects?filename=bad.pdf",
                    content=data,
                    headers={"Content-Type": "application/pdf"},
                )
                self.assertEqual(response.status_code, 422, response.text)
                self.assertEqual(set(response.json()), {"error"})
            for filename in ("../a.pdf", "C:\\secret.pdf", "a.txt"):
                response = client.post(
                    "/api/v1/projects",
                    params={"filename": filename},
                    content=self.pdf.read_bytes(),
                    headers={"Content-Type": "application/pdf"},
                )
                self.assertEqual(response.status_code, 400)
            self.assertEqual(
                client.post(
                    "/api/v1/projects?filename=a.pdf", content=self.pdf.read_bytes()
                ).status_code,
                400,
            )
            self.assertEqual(client.get("/api/v1/projects").json(), {"items": []})
        self.assertEqual(list((self.state / "uploads").iterdir()), [])

    def test_streaming_and_declared_upload_limits(self):
        with self.client(max_upload_bytes=1024) as client:
            response = client.post(
                "/api/v1/projects?filename=a.pdf",
                content=b"tiny",
                headers={"Content-Type": "application/pdf", "Content-Length": "1025"},
            )
            self.assertEqual(response.status_code, 413)
            response = client.post(
                "/api/v1/projects?filename=a.pdf",
                content=iter([b"%PDF-", b"x" * 1025]),
                headers={"Content-Type": "application/pdf"},
            )
            self.assertEqual(response.status_code, 413, response.text)
            self.assertEqual(client.get("/api/v1/projects").json(), {"items": []})

    def test_historical_sha_attachment_and_real_original(self):
        run = artifact_run(self.root / "run", self.pdf, current=False)
        imported = import_run(self.state, run)
        other = make_pdf(self.root / "other.pdf", text="Different original")
        with self.client() as client:
            prefix = f"/api/v1/projects/{imported.id}"
            page = client.get(prefix + "/pages/1").json()
            self.assertEqual(page["source_mode"], "historical")
            self.assertIsNone(page["image_url"])
            mismatch = client.post(
                prefix + "/pdf?filename=a.pdf",
                content=other.read_bytes(),
                headers={"Content-Type": "application/pdf"},
            )
            self.assertEqual(mismatch.status_code, 409)
            response = client.post(
                prefix + "/pdf?filename=a.pdf",
                content=self.pdf.read_bytes(),
                headers={"Content-Type": "application/pdf"},
            )
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()["pdf"]["available"])
            self.assertEqual(response.json()["acceptance"]["state"], "historical")
            self.assertEqual(
                client.get(prefix + "/pages/1").json()["source_mode"], "native"
            )
            self.assertEqual(
                client.post(
                    prefix + "/pdf?filename=a.pdf",
                    content=self.pdf.read_bytes(),
                    headers={"Content-Type": "application/pdf"},
                ).status_code,
                409,
            )

    def test_cli_import_original_validation_idempotence_and_private_copy(self):
        run = artifact_run(self.root / "run", self.pdf, current=False)
        other = make_pdf(self.root / "other.pdf", text="Wrong fingerprint")
        with self.assertRaises(WebError) as error:
            import_run(self.state, run, pdf_path=other)
        self.assertEqual(error.exception.code, "source_mismatch")
        service = WorkspaceService(self.state)
        self.assertEqual(service.project_ids(), [])
        self.assertEqual(list((self.state / "uploads").iterdir()), [])
        first = import_run(self.state, run, pdf_path=self.pdf)
        row = service.store.project(first.id)
        copied = self.state / row["pdf_rel"]
        self.assertEqual(copied.stat().st_mode & 0o777, 0o600)
        self.assertEqual(copied.read_bytes(), self.pdf.read_bytes())
        second = import_run(self.state, run, pdf_path=self.pdf)
        self.assertEqual(first.id, second.id)
        self.assertEqual(len(list((self.state / "uploads").iterdir())), 1)

    def test_rotation_annotations_and_actual_crops(self):
        rotated = make_pdf(self.root / "rotated.pdf", rotation=90)
        for rendered in (True, False):
            run = artifact_run(
                self.root / f"run-{rendered}", rotated, rendered=rendered
            )
            # Remove stored crop to prove the real PDF geometry crop path.
            binding_path = run / "structure_bindings/bindings.json"
            bindings = json.loads(binding_path.read_text())
            for binding in [
                *bindings["final_bindings"],
                *bindings["compound_catalog"]["entries"],
            ]:
                binding.pop("image_path", None)
            binding_path.write_text(json.dumps(bindings))
            structure_path = run / "structures/metadata.json"
            structures = json.loads(structure_path.read_text())
            for structure in structures["structures"]:
                structure.pop("image_path")
            structure_path.write_text(json.dumps(structures))
            imported = import_run(self.state, run, pdf_path=rotated)
            with self.client() as client:
                page = client.get(f"/api/v1/projects/{imported.id}/pages/1").json()
                self.assertEqual((page["width"], page["height"]), (200, 300))
                self.assertEqual(page["annotations"][0]["bbox"], [60, 20, 160, 120])
                image = client.get(
                    f"/api/v1/projects/{imported.id}/structures/Compound%201/image"
                )
                self.assertEqual(
                    image.status_code,
                    200,
                    image.text[:200] if image.status_code != 200 else "",
                )
                with Image.open(io.BytesIO(image.content)) as crop:
                    self.assertEqual(crop.size, (150, 150))
                    self.assertEqual(crop.getpixel((75, 75)), (255, 0, 0))

    def test_source_mutation_is_rejected_and_symlink_crops_are_not_served(self):
        run = artifact_run(self.root / "run", self.pdf, current=False)
        crop = run / "crop.png"
        crop.unlink()
        crop.symlink_to(self.pdf)
        imported = import_run(self.state, run, pdf_path=self.pdf)
        with self.client() as client:
            result = client.get(f"/api/v1/projects/{imported.id}/results").json()
            self.assertIn("image_unavailable", result["items"][0]["flags"])
            row = WorkspaceService(self.state).store.project(imported.id)
            (self.state / row["pdf_rel"]).write_bytes(b"changed original")
            response = client.get(f"/api/v1/projects/{imported.id}/pages/1/image")
            self.assertEqual(response.status_code, 409)
            self.assertNotIn(str(self.root), response.text)
