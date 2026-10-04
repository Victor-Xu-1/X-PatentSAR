"""Save-only overlays exercise SQLite, real RDKit and existing authenticated APIs."""

from __future__ import annotations

import copy
import csv
import hashlib
import io
import json
import unittest
from contextlib import contextmanager

from test_correction_structures import molfile
from test_web_support import WebFixture, artifact_run

from patent_sar_extractor.web.correction_models import CorrectionRequest
from patent_sar_extractor.web.errors import WebError
from patent_sar_extractor.web.service import WorkspaceService, import_run


class DirectEditTests(WebFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.run = artifact_run(self.root / "run", self.pdf)
        self.project = import_run(self.state, self.run, pdf_path=self.pdf)
        self.prefix = f"/api/v1/projects/{self.project.id}"
        self.path = self.prefix + "/structures/Compound%201/correction"

    @contextmanager
    def client(self, **kwargs):
        with super().client(**kwargs) as client:
            client.app.state.workspace.corrections.on_save = None
            yield client

    def save(self, client, document, *, legacy=False, **changes):
        fields = copy.deepcopy(document["values"])
        if legacy:
            fields = {
                key: fields[key] for key in ("display_id", "smiles", "activities")
            }
        fields.update(changes)
        return client.put(
            self.path,
            json={
                "expected_revision": document["revision"],
                "expected_source_fingerprint": document["source_fingerprint"],
                "fields": fields,
            },
        )

    def test_drawn_coordinates_manual_properties_audit_and_raw_provenance_survive_reopen(
        self,
    ):
        service = WorkspaceService(self.state)
        raw = service.store.compound(self.project.id, "Compound 1")
        originals = {
            path: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in self.run.rglob("*")
            if path.is_file()
        }
        block = molfile("CCO")
        overrides = {"logP": -1.27, "tpsa": None, "molecular_weight": 0}
        with self.client() as client:
            document = client.get(self.path).json()
            saved = self.save(
                client,
                document,
                structure_molfile=block,
                property_overrides=overrides,
                property_basis_smiles="OCC",
            )
            self.assertEqual(saved.status_code, 200, saved.text)
            saved = saved.json()
            self.assertEqual(saved["values"]["structure_molfile"], block)
            self.assertEqual(saved["values"]["property_basis_smiles"], "OCC")
            self.assertEqual(saved["values"]["smiles"], document["values"]["smiles"])
            row = client.get(self.prefix + "/results?q=Compound%201").json()["items"][0]
            self.assertEqual(row["structure_molfile"], block)
            self.assertEqual(row["property_overrides"], overrides)
            self.assertEqual(
                row["recognition"], json.loads(raw["payload"])["recognition"]
            )
            export = client.post(
                self.prefix + "/export",
                json={"format": "json", "compound_ids": ["Compound 1"]},
            ).json()
            self.assertTrue(export["review_only"])
            self.assertEqual(export["acceptance"]["state"], "accepted")
            self.assertEqual(export["items"][0]["property_overrides"], overrides)
        with self.client() as client:
            self.assertEqual(client.get(self.path).json(), saved)
            csv_reply = client.post(
                self.prefix + "/export",
                json={"format": "csv", "compound_ids": ["Compound 1"]},
            )
            exported = next(
                csv.DictReader(io.StringIO(csv_reply.content.decode("utf-8-sig")))
            )
            self.assertEqual(exported["LogP"], "-1.27")
            self.assertEqual(exported["TPSA_A2"], "")
            self.assertEqual(exported["MW_Dalton"], "0")
            self.assertEqual(
                exported["manual_property_keys"], "molecular_weight; logP; tpsa"
            )
            self.assertEqual(exported["property_basis_smiles"], "OCC")
            self.assertEqual(exported["admet_status"], "not_run")
            self.assertEqual(exported["admet_engine"], "")
            query = json.dumps(
                [{"column": "property:logP", "op": "eq", "value": "-1.27"}]
            )
            self.assertEqual(
                client.get(
                    self.prefix + "/results", params={"column_filters": query}
                ).json()["total"],
                1,
            )
            reset = self.save(client, saved, **saved["original"])
            self.assertEqual(reset.status_code, 200, reset.text)
            row = client.get(self.prefix + "/results?q=Compound%201").json()["items"][0]
            self.assertNotIn("structure_molfile", row)
            self.assertNotIn("property_overrides", row)
        self.assertEqual(service.store.compound(self.project.id, "Compound 1"), raw)
        self.assertEqual(
            originals,
            {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in originals},
        )
        with service.store.connect() as connection:
            rows = connection.execute(
                "SELECT fields FROM correction_audit ORDER BY revision"
            ).fetchall()
            self.assertEqual(len(rows), 2)
            self.assertEqual(json.loads(rows[0][0])["property_overrides"], overrides)
            self.assertEqual(json.loads(rows[0][0])["structure_molfile"], block)

    def test_legacy_omission_keeps_addons_only_for_unchanged_graph(self):
        with self.client() as client:
            document = client.get(self.path).json()
            block = molfile("CCO")
            first = self.save(
                client,
                document,
                structure_molfile=block,
                property_overrides={"logP": 3},
                property_basis_smiles="CCO",
            )
            self.assertEqual(first.status_code, 200, first.text)
            second = self.save(
                client, first.json(), legacy=True, display_id="Old client", smiles="OCC"
            )
            self.assertEqual(second.status_code, 200, second.text)
            values = second.json()["values"]
            self.assertEqual(values["structure_molfile"], block)
            self.assertEqual(values["property_overrides"], {"logP": 3})
            third = self.save(client, second.json(), legacy=True, smiles="CCN")
            self.assertEqual(third.status_code, 200, third.text)
            self.assertIsNone(third.json()["values"]["structure_molfile"])
            self.assertEqual(third.json()["values"]["property_overrides"], {})
            self.assertIsNone(third.json()["values"]["property_basis_smiles"])

    def test_raw_strings_survive_equivalent_graph_saves_and_only_true_changes_enqueue(
        self,
    ):
        calls = []

        def callback(connection, _project, _compound, effective):
            self.assertTrue(connection.in_transaction)
            calls.append(effective.smiles)

        service = WorkspaceService(self.state, correction_on_save=callback)
        document = service.get_correction(self.project.id, "Compound 1")

        def put(smiles, **addons):
            nonlocal document
            body = {**document.values.model_dump(), "smiles": smiles, **addons}
            request = CorrectionRequest.model_validate(
                {
                    "expected_revision": document.revision,
                    "expected_source_fingerprint": document.source_fingerprint,
                    "fields": body,
                }
            )
            document = service.put_correction(self.project.id, "Compound 1", request)

        put("OCC", structure_molfile=molfile("CCO"))
        self.assertEqual(document.values.smiles, "OCC")
        self.assertEqual(calls, [])
        put(
            "NCC",
            structure_molfile=molfile("CCN"),
            property_overrides={},
            property_basis_smiles=None,
        )
        put(
            "CCN",
            structure_molfile=molfile("CCN"),
            property_overrides={"logP": 1},
            property_basis_smiles="CCN",
        )
        self.assertEqual(calls, ["NCC"])
        before = document
        service.corrections.on_save = lambda *_: (_ for _ in ()).throw(
            WebError(409, "queue_busy", "Controlled enqueue failure")
        )
        with self.assertRaises(WebError):
            put(
                "CCCl",
                structure_molfile=None,
                property_overrides={},
                property_basis_smiles=None,
            )
        self.assertEqual(service.get_correction(self.project.id, "Compound 1"), before)

    def test_stale_overlay_and_conflicted_save_never_apply_manual_addons(self):
        with self.client() as client:
            first = client.get(self.path).json()
            saved = self.save(
                client,
                first,
                structure_molfile=molfile("CCO"),
                property_overrides={"logP": 2},
                property_basis_smiles="CCO",
            )
            self.assertEqual(saved.status_code, 200, saved.text)
            self.assertEqual(
                self.save(client, first, display_id="Conflict").status_code, 409
            )
        WorkspaceService(self.state).refresh(self.project.id)
        with self.client() as client:
            row = client.get(self.prefix + "/results?q=Compound%201").json()["items"][0]
            self.assertTrue(row["correction"]["stale"])
            self.assertNotIn("structure_molfile", row)
            self.assertNotIn("property_overrides", row)
