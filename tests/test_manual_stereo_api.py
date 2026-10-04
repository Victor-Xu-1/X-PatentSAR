"""Manual edit/save/reload/redraw/export with real authenticated API and SQLite."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import unittest
from unittest.mock import Mock

from manual_stereo_fixtures import moved_block, structure_block, unknown_block
from test_web_support import WebFixture, artifact_run

from patent_sar_extractor.web.service import WorkspaceService, import_run


class ManualStereoApiTests(WebFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.run = artifact_run(self.root / "controlled-run", self.pdf)
        self.project = import_run(self.state, self.run, pdf_path=self.pdf)
        self.prefix = f"/api/v1/projects/{self.project.id}"

    def document(self, client, compound="Compound 1"):
        return client.get(f"{self.prefix}/structures/{compound}/correction").json()

    def save(self, client, *, compound="Compound 1", **changes):
        document = self.document(client, compound)
        response = client.put(
            f"{self.prefix}/structures/{compound}/correction",
            json={
                "expected_revision": document["revision"],
                "expected_source_fingerprint": document["source_fingerprint"],
                "fields": {**document["values"], **changes},
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def results(self, client):
        return client.get(self.prefix + "/results").json()["items"]

    def artifacts(self):
        return {
            str(path.relative_to(self.run)): hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for path in self.run.rglob("*")
            if path.is_file()
        }

    def test_unknown_save_reload_redraw_and_both_exports_preserve_raw_source(self):
        before = self.artifacts()
        raw = WorkspaceService(self.state).store.compound(self.project.id, "Compound 1")
        for kind in ("tetra", "double", "mixed"):
            for version in (False, True):
                with self.subTest(kind=kind, v3000=version), self.client() as client:
                    callback = Mock()
                    client.app.state.workspace.corrections.on_save = callback
                    smiles, block = unknown_block(kind, v3000=version)
                    document = self.save(client, smiles=smiles, structure_molfile=block)
                    self.assertEqual(document["values"]["structure_molfile"], block)
                    callback.assert_not_called()
                    row = next(
                        row for row in self.results(client) if row["id"] == "Compound 1"
                    )
                    self.assertEqual(row["smiles"], smiles)
                    self.assertEqual(row["structure_molfile"], block)
                    self.assertEqual(row["admet"]["status"], "unavailable")
                    self.assertEqual(
                        row["admet"]["error"]["code"], "manual_stereo_unresolved"
                    )
                    drawing = client.get(row["redraw_image_url"])
                    self.assertEqual(
                        drawing.status_code,
                        200,
                        drawing.text[:100] if drawing.status_code != 200 else "",
                    )
                    self.assertIn(
                        "no-store", drawing.headers["cache-control"].split(", ")
                    )
                    self.assertTrue(drawing.content.startswith(b"\x89PNG\r\n\x1a\n"))
                    for format_name in ("json", "csv"):
                        response = client.post(
                            self.prefix + "/export",
                            json={
                                "format": format_name,
                                "compound_ids": ["Compound 1"],
                            },
                        )
                        self.assertEqual(response.status_code, 200, response.text[:100])
                        if format_name == "json":
                            self.assertTrue(response.json()["review_only"])
                            exported = response.json()["items"][0]
                            self.assertEqual(exported["structure_molfile"], block)
                        else:
                            exported = next(
                                csv.DictReader(
                                    io.StringIO(response.content.decode("utf-8-sig"))
                                )
                            )
                            self.assertEqual(
                                json.loads(exported["structure_molfile_json"]), block
                            )
                            self.assertEqual(exported["review_only"], "True")
                    self.assertEqual(exported["smiles"], smiles)
                reloaded = WorkspaceService(self.state).get_correction(
                    self.project.id, "Compound 1"
                )
                self.assertEqual(reloaded.values.structure_molfile, block)
        self.assertEqual(self.artifacts(), before)
        self.assertEqual(
            WorkspaceService(self.state).store.compound(self.project.id, "Compound 1"),
            raw,
        )

    def test_same_smiles_stereo_and_coordinate_edits_invalidate_old_drawing_urls(self):
        with self.client() as client:
            client.app.state.workspace.corrections.on_save = None
            for kind in ("tetra", "double"):
                smiles, block = unknown_block(kind, v3000=True)
                self.save(client, smiles=smiles, structure_molfile=None)
                row = next(
                    row for row in self.results(client) if row["id"] == "Compound 1"
                )
                original_url = row["redraw_image_url"]
                self.assertIn(hashlib.sha256(smiles.encode()).hexdigest(), original_url)
                self.save(client, smiles=smiles, structure_molfile=block)
                row = next(
                    row for row in self.results(client) if row["id"] == "Compound 1"
                )
                manual_url = row["redraw_image_url"]
                self.assertNotEqual(original_url, manual_url)
                self.assertEqual(client.get(original_url).status_code, 409)
                self.assertEqual(client.get(manual_url).status_code, 200)
                self.assertEqual(client.get(manual_url.split("?")[0]).status_code, 422)
                self.save(client, structure_molfile=moved_block(block, v3000=True))
                self.assertEqual(client.get(manual_url).status_code, 409)
                current_url = next(
                    row for row in self.results(client) if row["id"] == "Compound 1"
                )["redraw_image_url"]
                self.assertEqual(client.get(current_url).status_code, 200)

    def test_abs_group_is_exact_and_drawing_only_edits_do_not_call_prediction(self):
        with self.client() as client:
            client.app.state.workspace.corrections.on_save = None
            smiles = "F[C@H](Cl)Br"
            block = structure_block(smiles + " |a:1|", v3000=True)
            self.save(client, smiles=smiles, structure_molfile=block)
            callback = Mock()
            client.app.state.workspace.corrections.on_save = callback
            self.save(client, structure_molfile=moved_block(block, v3000=True))
            self.save(
                client,
                property_overrides={"logP": 0, "tpsa": None},
                property_basis_smiles=smiles,
            )
            callback.assert_not_called()
            exported = client.post(
                self.prefix + "/export",
                json={"format": "json", "compound_ids": ["Compound 1"]},
            ).json()
            self.assertIn("MDLV30/STEABS", exported["items"][0]["structure_molfile"])
            self.assertEqual(
                exported["items"][0]["property_overrides"], {"logP": 0, "tpsa": None}
            )

    def test_fraction_ids_with_identical_graphs_and_unknown_stereo_remain_separate(
        self,
    ):
        with self.client() as client:
            client.app.state.workspace.corrections.on_save = None
            smiles, block = unknown_block("tetra", v3000=True)
            for index, fraction in ((1, "fraction-A"), (2, "fraction-B")):
                self.save(
                    client,
                    compound=f"Compound {index}",
                    display_id=fraction,
                    smiles=smiles,
                    structure_molfile=block,
                )
            rows = self.results(client)
            self.assertEqual(len(rows), 2)
            self.assertEqual({row["id"] for row in rows}, {"Compound 1", "Compound 2"})
            self.assertEqual(
                {row["display_id"] for row in rows}, {"fraction-A", "fraction-B"}
            )
            exported = client.post(
                self.prefix + "/export", json={"format": "json", "compound_ids": []}
            ).json()
            self.assertEqual(len(exported["items"]), 2)

    def test_invalid_stereo_or_graph_cannot_save_or_change_audit(self):
        with self.client() as client:
            document = self.document(client)
            for smiles, block in (
                ("CCO", structure_block("CCN")),
                ("F[C@H](Cl)Br", unknown_block("tetra", v3000=True)[1]),
                ("F/C=C/F", unknown_block("double")[1]),
                ("F[C@H](Cl)Br", structure_block("F[C@H](Cl)Br |o1:1|", v3000=True)),
            ):
                response = client.put(
                    f"{self.prefix}/structures/Compound 1/correction",
                    json={
                        "expected_revision": document["revision"],
                        "expected_source_fingerprint": document["source_fingerprint"],
                        "fields": {
                            **document["values"],
                            "smiles": smiles,
                            "structure_molfile": block,
                        },
                    },
                )
                self.assertEqual(response.status_code, 422)
            self.assertEqual(self.document(client)["revision"], 0)
        with WorkspaceService(self.state).store.connect() as connection:
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM correction_audit").fetchone()[
                    0
                ],
                0,
            )
