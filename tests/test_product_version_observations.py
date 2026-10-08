"""Source-bound observation, manual overlay and audit release regressions."""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from product_version_support import (
    OLD_RELEASE,
    ProductVersionObservationFixture,
    incompatible_identities,
)
from test_prediction_support import controlled_stage

from patent_sar_extractor import contracts as core
from patent_sar_extractor.artifact_io import write_json_atomic
from patent_sar_extractor.web.admet_history import read_admet_stage
from patent_sar_extractor.web.correction_models import CorrectionRequest, EditableFields
from patent_sar_extractor.web.correction_storage import correction_source_fingerprint
from patent_sar_extractor.web.errors import WebError
from patent_sar_extractor.web.prediction_identity import compound_prediction_eligible
from patent_sar_extractor.web.property_values import effective_property_values
from patent_sar_extractor.web.storage import encode


class ReleaseObservationTests(ProductVersionObservationFixture, unittest.TestCase):
    def test_label_only_reads_preserve_projection_properties_recognition_and_history(
        self,
    ):
        row, root, source, prediction, descriptors, _, _ = self.seed_old()
        before = self.saved_rows()
        files = {
            path: path.read_bytes()
            for path in (
                self.pdf,
                root / "admet-stage.json",
                self.state / "job-history" / f"{row['id']}-admet.json",
                *(path for path in self.run.rglob("*") if path.is_file()),
            )
        }
        with patch.object(
            self.service,
            "refresh",
            side_effect=AssertionError("No label-only projection rebuild"),
        ):
            self.service.project(self.project.id)
            item = self.service.effective_compound(self.project.id, "Compound 1")
        self.assertEqual(item.recognition.status, "valid")
        inputs = [("Compound 1", source, "CCO")]
        self.assertEqual(
            self.service.predictions.summaries(self.project.id, inputs)["Compound 1"],
            prediction,
        )
        self.assertEqual(
            self.service.descriptors.summaries(self.project.id, inputs)["Compound 1"],
            descriptors,
        )
        stage, core_completed = read_admet_stage(row, root, state_root=self.state)
        self.assertEqual(stage, controlled_stage())
        self.assertFalse(core_completed)
        self.assertEqual(self.saved_rows(), before)
        self.assertEqual({path: path.read_bytes() for path in files}, files)

    def test_label_only_upgrade_preserves_manual_source_hash_values_and_audit(self):
        _, _, source, prediction, descriptors, _, _ = self.seed_old()
        with patch.object(core, "__version__", OLD_RELEASE):
            document = self.service.get_correction(self.project.id, "Compound 1")
            self.service.put_correction(
                self.project.id,
                "Compound 1",
                CorrectionRequest(
                    expected_revision=document.revision,
                    expected_source_fingerprint=document.source_fingerprint,
                    fields=EditableFields(
                        **{
                            **document.values.model_dump(),
                            "display_id": "Reviewed original identifier",
                            "property_overrides": {"logP": 0, "tpsa": None},
                            "property_basis_smiles": "CCO",
                        }
                    ),
                ),
            )
        before = self.saved_rows()
        original = self.service.store.project(self.project.id)
        raw = self.service.store.compound(self.project.id, "Compound 1")
        self.assertEqual(correction_source_fingerprint(original, raw), source)
        with patch.object(
            self.service,
            "refresh",
            side_effect=AssertionError(
                "Release changes must not replace producer identity"
            ),
        ):
            item = self.service.compounds(self.project.id)[0]
        self.assertFalse(item.correction.stale)
        self.assertEqual(item.display_id, "Reviewed original identifier")
        self.assertEqual(item.admet, prediction)
        self.assertEqual(item.descriptors, descriptors)
        values = effective_property_values(item)
        self.assertEqual(values["logP"], 0)
        self.assertIsNone(values["tpsa"])
        after = self.service.store.project(self.project.id)
        self.assertEqual(correction_source_fingerprint(after, raw), source)
        self.assertEqual(after["snapshot"], original["snapshot"])
        self.assertEqual(self.saved_rows(), before)

    def test_recognition_and_history_reject_invalid_or_scientifically_foreign_runtime(
        self,
    ):
        row, root, _, _, _, _, _ = self.seed_old()
        history = self.state / "job-history" / f"{row['id']}-admet.json"
        original = history.read_bytes()
        for reason, identity in incompatible_identities():
            packet = json.loads(original)
            packet["runtime_identity"] = identity
            write_json_atomic(history, packet)
            with self.service.store.connect(write=True) as connection:
                connection.execute(
                    "UPDATE compound_recognitions SET runtime_identity=?",
                    (encode(identity),),
                )
            with self.subTest(reason=reason):
                item = self.service.effective_compound(self.project.id, "Compound 1")
                self.assertEqual(item.recognition.status, "unavailable")
                self.assertIsNone(item.smiles)
                self.assertIsNone(read_admet_stage(row, root, state_root=self.state)[0])

    def test_old_release_does_not_bypass_a_new_stereo_epoch(self):
        row, _, _, _, _, _, _ = self.seed_old()
        source = {
            path: path.read_bytes() for path in self.run.rglob("*") if path.is_file()
        }
        with (
            patch.object(
                core, "STEREO_EVIDENCE_VERSION", core.STEREO_EVIDENCE_VERSION + 1
            ),
            patch.object(
                self.service,
                "refresh",
                side_effect=AssertionError("Do not replace raw projection rows"),
            ),
        ):
            self.assertEqual(
                self.service.project(self.project.id).acceptance.state, "historical"
            )
            item = self.service.effective_compound(self.project.id, "Compound 1")
            self.assertFalse(compound_prediction_eligible(item))
        self.assertEqual(self.service.store.job(row["id"]), row)
        self.assertEqual({path: path.read_bytes() for path in source}, source)

    def test_old_producer_can_publish_but_source_and_active_job_cas_still_gate(self):
        row, _, source, prediction, descriptors, record, crop = self.seed_old(
            terminal=False
        )
        before_spec = row["spec"]
        self.service.predictions.put(self.project.id, "Compound 1", prediction)
        self.service.descriptors.put(self.project.id, "Compound 1", descriptors)
        self.recognitions.put(
            self.project.id,
            "Compound 1",
            source=source,
            crop=crop,
            record=record,
            job_id=row["id"],
        )
        self.assertEqual(self.service.store.job(row["id"])["spec"], before_spec)
        before = self.saved_rows()
        with self.assertRaises(WebError) as error:
            self.service.predictions.put(
                self.project.id,
                "Compound 1",
                prediction.model_copy(update={"source_fingerprint": "0" * 64}),
            )
        self.assertEqual(error.exception.code, "admet_binding")
        with self.assertRaises(WebError) as error:
            self.recognitions.put(
                self.project.id,
                "Compound 1",
                source=source,
                crop="0" * 64,
                record=record,
                job_id=row["id"],
            )
        self.assertEqual(error.exception.code, "recognition_source_changed")
        self.assertEqual(self.saved_rows(), before)
        with self.service.store.connect(write=True) as connection:
            connection.execute(
                "UPDATE jobs SET status='complete' WHERE id=?", (row["id"],)
            )
        with self.assertRaises(WebError) as error:
            self.service.descriptors.put(self.project.id, "Compound 1", descriptors)
        self.assertEqual(error.exception.code, "admet_binding")

    def test_saved_packets_reject_scientific_schema_engine_and_producer_changes(self):
        row, root, source, _, _, _, _ = self.seed_old()
        inputs = [("Compound 1", source, "CCO")]
        with self.service.store.connect() as connection:
            saved = connection.execute(
                "SELECT payload FROM molecular_descriptors"
            ).fetchone()[0]
        for field in ("runtime", "epoch", "schema", "rdkit", "source", "graph"):
            packet = json.loads(saved)
            if field == "runtime":
                packet["runtime_identity"]["ruleset"]["version"] = "2.0.0"
            elif field == "epoch":
                packet["epoch"] = "0" * 64
            elif field == "schema":
                packet["schema"]["version"] = 2
            elif field == "rdkit":
                packet["observation"]["engine"]["version"] = "foreign"
            elif field == "source":
                packet["observation"]["source_fingerprint"] = "0" * 64
            else:
                packet["observation"]["smiles_sha256"] = "0" * 64
            with self.service.store.connect(write=True) as connection:
                connection.execute(
                    "UPDATE molecular_descriptors SET payload=?", (encode(packet),)
                )
            with self.subTest(field=field):
                result = self.service.descriptors.summaries(self.project.id, inputs)[
                    "Compound 1"
                ]
                self.assertEqual(result.status, "failed")
                self.assertEqual(result.properties, [])
        with self.service.store.connect(write=True) as connection:
            connection.execute("UPDATE molecular_descriptors SET payload=?", (saved,))
        for reason, identity in incompatible_identities():
            spec = json.loads(row["spec"])
            spec["runtime_identity"] = identity
            with self.service.store.connect(write=True) as connection:
                connection.execute(
                    "UPDATE jobs SET spec=? WHERE id=?", (encode(spec), row["id"])
                )
            with self.subTest(reason=reason):
                self.assertEqual(
                    self.service.predictions.summaries(self.project.id, inputs)[
                        "Compound 1"
                    ].status,
                    "failed",
                )
                self.assertEqual(
                    self.service.descriptors.summaries(self.project.id, inputs)[
                        "Compound 1"
                    ].status,
                    "failed",
                )
                self.assertIsNone(
                    read_admet_stage(
                        self.service.store.job(row["id"]), root, state_root=self.state
                    )[0]
                )


if __name__ == "__main__":
    unittest.main()
