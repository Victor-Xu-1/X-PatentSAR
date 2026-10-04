"""Exact-original recovery of corrupt addons; no production data or model work."""

from __future__ import annotations

import copy
import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

from test_correction_structures import molfile
from test_prediction_support import PredictionFixture

from patent_sar_extractor.web.correction_models import CorrectionRequest
from patent_sar_extractor.web.correction_storage import correction_source_fingerprint
from patent_sar_extractor.web.corrections import original_fields
from patent_sar_extractor.web.errors import WebError
from patent_sar_extractor.web.models import Compound
from patent_sar_extractor.web.prediction_jobs import enqueue_prediction
from patent_sar_extractor.web.service import WorkspaceService
from patent_sar_extractor.web.storage import encode


class CorruptAddonRecoveryTests(PredictionFixture, unittest.TestCase):
    def seed(self, mutation="molfile"):
        original = self.service.get_correction(self.project.id, "Compound 1")
        saved = self.service.put_correction(
            self.project.id,
            "Compound 1",
            CorrectionRequest(
                expected_revision=0,
                expected_source_fingerprint=original.source_fingerprint,
                fields=original.values.model_copy(
                    update={
                        "smiles": "CCN",
                        "structure_molfile": molfile("CCN", v3000=True),
                        "property_overrides": {"logP": 1},
                        "property_basis_smiles": "CCN",
                    }
                ),
            ),
        )
        with self.service.store.connect(write=True) as connection:
            fields = saved.values.model_dump()
            if mutation == "molfile":
                fields["structure_molfile"] = "Malformed MDL text"
            else:
                fields["property_basis_smiles"] = "CCO"
            connection.execute(
                "UPDATE corrections SET fields=? WHERE project_id=? AND compound_id=?",
                (encode(fields), self.project.id, "Compound 1"),
            )
        request = CorrectionRequest(
            expected_revision=saved.revision,
            expected_source_fingerprint=saved.source_fingerprint,
            fields=original.original,
        )
        return original, request

    def snapshot(self):
        with self.service.store.connect() as connection:
            return {
                name: [
                    dict(row)
                    for row in connection.execute(
                        f"SELECT * FROM {name} ORDER BY rowid"
                    )
                ]
                for name in ("corrections", "correction_audit", "jobs")
            }

    def assert_get_blocked(self):
        with self.assertRaises(WebError) as caught:
            self.service.get_correction(self.project.id, "Compound 1")
        self.assertEqual(
            (caught.exception.status, caught.exception.code),
            (422, "invalid_correction"),
        )

    def put(self, request):
        return self.service.put_correction(self.project.id, "Compound 1", request)

    def test_malformed_molfile_get_stays_blocked_then_exact_reset_is_audited(self):
        original, request = self.seed()
        self.assert_get_blocked()
        before = self.snapshot()
        raw = self.service.store.compound(self.project.id, "Compound 1")
        restored = self.put(request)
        self.assertEqual(restored.values.model_dump(), original.original.model_dump())
        self.assertEqual(restored.revision, 2)
        self.assertFalse(restored.has_changes)
        self.assertEqual(
            self.snapshot()["correction_audit"][:1], before["correction_audit"]
        )
        self.assertEqual(len(self.snapshot()["correction_audit"]), 2)
        self.assertEqual(
            self.service.get_correction(self.project.id, "Compound 1"), restored
        )
        self.assertEqual(
            self.service.store.compound(self.project.id, "Compound 1"), raw
        )

    def test_inconsistent_nonempty_basis_get_stays_blocked_then_exact_reset_is_audited(
        self,
    ):
        original, request = self.seed("basis")
        self.assert_get_blocked()
        restored = self.put(request)
        self.assertEqual(restored.values, original.original)
        self.assertEqual(restored.values.property_overrides, {})
        self.assertIsNone(restored.values.property_basis_smiles)
        self.assertEqual(len(self.snapshot()["correction_audit"]), 2)

    def test_authenticated_api_get_stays_error_until_exact_original_put(self):
        original, request = self.seed()
        endpoint = (
            f"/api/v1/projects/{self.project.id}/structures/Compound%201/correction"
        )
        with self.client() as client:
            client.app.state.workspace.corrections.on_save = None
            failed = client.get(endpoint)
            self.assertEqual(failed.status_code, 422)
            self.assertEqual(failed.json()["error"]["code"], "invalid_correction")
            self.assertNotIn("values", failed.json())
            changed = request.model_dump()
            changed["fields"]["display_id"] = "Not an exact reset"
            self.assertEqual(client.put(endpoint, json=changed).status_code, 422)
            restored = client.put(endpoint, json=request.model_dump())
            self.assertEqual(restored.status_code, 200, restored.text)
            self.assertEqual(restored.json()["values"], original.original.model_dump())
            self.assertFalse(restored.json()["has_changes"])
            self.assertEqual(client.get(endpoint).json(), restored.json())

    def test_changed_source_requires_current_cas_and_preserves_stale_reset_semantics(
        self,
    ):
        _, request = self.seed()
        audit = self.snapshot()["correction_audit"]
        self.service.refresh(self.project.id)
        raw = self.service.store.compound(self.project.id, "Compound 1")
        source = correction_source_fingerprint(
            self.service.store.project(self.project.id), raw
        )
        self.assertNotEqual(source, request.expected_source_fingerprint)
        with self.assertRaises(WebError) as caught:
            self.put(request)
        self.assertEqual(caught.exception.code, "correction_source_conflict")
        callback = Mock()
        self.service.corrections.on_save = callback
        restored = self.put(
            request.model_copy(
                update={
                    "expected_source_fingerprint": source,
                    "fields": original_fields(
                        Compound.model_validate_json(raw["payload"])
                    ),
                }
            )
        )
        self.assertEqual(restored.source_fingerprint, source)
        self.assertFalse(restored.has_changes)
        self.assertEqual(self.snapshot()["correction_audit"][:1], audit)
        callback.assert_not_called()

    def test_nonoriginal_edits_or_addons_cannot_use_recovery(self):
        _, request = self.seed()
        before = self.snapshot()
        for changes in (
            {"display_id": "Other label"},
            {"smiles": "OCC"},
            {"activities": []},
            {"structure_molfile": molfile("CCO")},
            {"property_overrides": {"logP": 0}, "property_basis_smiles": "CCO"},
        ):
            with self.subTest(changes=changes), self.assertRaises(WebError) as caught:
                self.put(
                    request.model_copy(
                        update={"fields": request.fields.model_copy(update=changes)}
                    )
                )
            self.assertEqual(caught.exception.code, "invalid_correction")
            self.assertEqual(self.snapshot(), before)

    def test_revision_and_source_cas_conflicts_precede_corrupt_addon_parsing(self):
        _, request = self.seed()
        before = self.snapshot()
        callback = Mock()
        self.service.corrections.on_save = callback
        for changes, code in (
            ({"expected_revision": 0}, "correction_conflict"),
            ({"expected_source_fingerprint": "0" * 64}, "correction_source_conflict"),
        ):
            with self.subTest(code=code), self.assertRaises(WebError) as caught:
                self.put(request.model_copy(update=changes))
            self.assertEqual(
                (caught.exception.status, caught.exception.code), (409, code)
            )
            self.assertEqual(self.snapshot(), before)
        callback.assert_not_called()

    def test_active_job_blocks_recovery_without_writes(self):
        _, request = self.seed()
        with self.service.store.connect(write=True) as connection:
            enqueue_prediction(
                self.service.store,
                connection,
                self.project.id,
                compound_ids=("Compound 1",),
            )
        before = self.snapshot()
        with self.assertRaises(WebError) as caught:
            self.put(request)
        self.assertEqual(caught.exception.code, "correction_busy")
        self.assertEqual(self.snapshot(), before)

    def test_failed_enqueue_rolls_back_reset_audit_and_job_then_retry_is_atomic(self):
        _, request = self.seed()
        before = self.snapshot()

        def enqueue(connection, project_id, compound_id, compound):
            self.assertEqual(compound.smiles, "CCO")
            enqueue_prediction(
                self.service.store, connection, project_id, compound_ids=(compound_id,)
            )

        def fail(connection, project_id, compound_id, compound):
            enqueue(connection, project_id, compound_id, compound)
            raise WebError(503, "controlled_enqueue_failure", "Controlled rollback")

        self.service.corrections.on_save = fail
        with self.assertRaises(WebError) as caught:
            self.put(request)
        self.assertEqual(caught.exception.code, "controlled_enqueue_failure")
        self.assertEqual(self.snapshot(), before)
        self.assert_get_blocked()
        self.service.corrections.on_save = enqueue
        restored = self.put(request)
        self.assertEqual(restored.revision, 2)
        state = self.snapshot()
        self.assertEqual(len(state["jobs"]), 1)
        self.assertEqual(
            json.loads(state["jobs"][0]["spec"])["admet_compounds"], ["Compound 1"]
        )
        self.assertEqual(state["correction_audit"][:1], before["correction_audit"])
        self.assertEqual(len(state["correction_audit"]), 2)

    def test_rejected_original_is_restored_as_evidence_not_manual_valid_chemistry(self):
        raw = self.service.store.compound(self.project.id, "Compound 1")
        payload = json.loads(raw["payload"])
        payload["smiles"] = "*C"
        payload["recognition"] = {
            "status": "invalid",
            "quality_flag": "original_rejected",
        }
        with self.service.store.connect(write=True) as connection:
            connection.execute(
                "UPDATE compounds SET payload=? WHERE project_id=? AND id=?",
                (encode(payload), self.project.id, "Compound 1"),
            )
        original, request = self.seed()
        callback = Mock()
        self.service.corrections.on_save = callback
        restored = self.put(request)
        effective = self.service.effective_compound(self.project.id, "Compound 1")
        self.assertEqual(restored.values, original.original)
        self.assertEqual(effective.smiles, "*C")
        self.assertEqual(effective.recognition.status, "invalid")
        self.assertEqual(effective.recognition.quality_flag, "original_rejected")
        callback.assert_not_called()
        self.assertFalse(effective.correction.has_changes)

    def test_invalid_nonaddon_or_baseline_records_do_not_gain_a_general_bypass(self):
        _, request = self.seed()
        before = self.snapshot()
        for column, value in (
            ("fields", '{"display_id":""}'),
            ("original_fields", "null"),
        ):
            with self.subTest(column=column):
                with self.service.store.connect(write=True) as connection:
                    connection.execute(f"UPDATE corrections SET {column}=?", (value,))
                state = self.snapshot()
                with self.assertRaises(WebError):
                    self.put(request)
                self.assertEqual(self.snapshot(), state)
                with self.service.store.connect(write=True) as connection:
                    record = before["corrections"][0]
                    connection.execute(
                        "UPDATE corrections SET fields=?,original_fields=?",
                        (record["fields"], record["original_fields"]),
                    )

    def test_concurrent_recovery_has_one_cas_winner_and_one_audit_append(self):
        _, request = self.seed()

        def attempt():
            service = WorkspaceService(self.state)
            try:
                service.put_correction(
                    self.project.id, "Compound 1", copy.deepcopy(request)
                )
                return "ok"
            except WebError as exc:
                return exc.code

        with ThreadPoolExecutor(max_workers=2) as executor:
            statuses = list(executor.map(lambda _: attempt(), range(2)))
        self.assertCountEqual(statuses, ["ok", "correction_conflict"])
        self.assertEqual(len(self.snapshot()["correction_audit"]), 2)


if __name__ == "__main__":
    unittest.main()
