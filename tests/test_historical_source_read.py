"""Historical originals remain inspectable without acquiring current source proof."""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

import test_uniform_recognition as uniform_tests
from test_prediction_support import PredictionFixture

from patent_sar_extractor import contracts
from patent_sar_extractor.web.completion_inputs import completion_inputs
from patent_sar_extractor.web.compound_catalog import read_compound_catalog
from patent_sar_extractor.web.correction_models import CorrectionRequest, EditableFields
from patent_sar_extractor.web.errors import WebError
from patent_sar_extractor.web.recognition_sources import recognition_sources


class HistoricalSourceReadTests(PredictionFixture, unittest.TestCase):
    @staticmethod
    def downgrade(path, payload):
        payload["schema"]["version"] = contracts.BINDINGS_SCHEMA_VERSION - 1
        for source in payload["compound_catalog"]["entries"]:
            source["binding_rule"] = "unproved_imported_source"
            source.pop("exact_caption_evidence", None)
        path.write_text(json.dumps(payload))

    def old_sources(self, *, current=False):
        path, payload, _ = uniform_tests.UniformRecognitionTests.prepare(self)
        if not current:
            payload["schema"]["version"] = contracts.BINDINGS_SCHEMA_VERSION - 1
        for source in payload["compound_catalog"]["entries"]:
            source["binding_rule"] = "unproved_imported_source"
            source.pop("exact_caption_evidence", None)
        path.write_text(json.dumps(payload))
        return path, payload

    def test_old_catalog_semantics_do_not_block_original_and_raw_review(self):
        _, payload = self.old_sources()
        # This really reproduces the strict reader rejection, not an absent or
        # empty catalogue that was already supported.
        structures = json.loads((self.run / "structures/metadata.json").read_text())[
            "structures"
        ]
        with self.assertRaises(WebError):
            read_compound_catalog(payload, structures)
        before = {
            path: path.read_bytes() for path in self.run.rglob("*") if path.is_file()
        }
        self.service.refresh(self.project.id)
        project = self.service.project(self.project.id)
        self.assertEqual(project.pdf.page_count, 1)
        self.assertTrue(project.pdf.available)
        result = self.service.results(self.project.id)
        first = next(row for row in result.items if row.id == "Compound 1")
        self.assertEqual(first.confidence.level, "review")
        self.assertIn("historical_identity", first.flags)
        self.assertEqual(first.recognition.status, "unavailable")
        self.assertIsNone(first.smiles)
        self.assertEqual(first.admet.properties, [])
        self.assertNotEqual(project.acceptance.state, "accepted")
        self.assertEqual({path: path.read_bytes() for path in before}, before)

    def test_old_numbered_sources_without_activity_keep_identity_and_manual_audit(self):
        path, payload, _ = uniform_tests.UniformRecognitionTests.prepare(self)
        document = self.service.get_correction(self.project.id, "Compound 8")
        self.service.put_correction(
            self.project.id,
            "Compound 8",
            CorrectionRequest(
                expected_revision=document.revision,
                expected_source_fingerprint=document.source_fingerprint,
                fields=EditableFields(
                    **{
                        **document.values.model_dump(),
                        "display_id": "Human review name",
                    }
                ),
            ),
        )
        with self.service.store.connect() as connection:
            before = [
                tuple(row)
                for row in connection.execute("SELECT * FROM correction_audit")
            ]
        self.downgrade(path, payload)
        self.service.refresh(self.project.id)
        rows = self.service.results(self.project.id).items
        source_only = next(row for row in rows if row.id == "Compound 8")
        self.assertEqual(source_only.structure_id, "numbered-without-activity")
        self.assertEqual(source_only.activities, [])
        self.assertEqual(source_only.recognition.status, "unavailable")
        self.assertEqual(source_only.admet.properties, [])
        with self.service.store.connect() as connection:
            after = [
                tuple(row)
                for row in connection.execute("SELECT * FROM correction_audit")
            ]
        self.assertEqual(before, after)

    def test_current_invalid_original_proof_still_refuses_publication(self):
        self.old_sources(current=True)
        with self.assertRaises(WebError) as rejected:
            self.service.refresh(self.project.id)
        self.assertEqual(rejected.exception.code, "invalid_compound_catalog")

    def test_historical_review_retains_structural_and_cross_owner_guards(self):
        path, original = self.old_sources()
        for problem in (
            "duplicate_id",
            "foreign_image",
            "foreign_alias",
            "malformed_labels",
        ):
            with self.subTest(problem=problem):
                payload = json.loads(json.dumps(original))
                entries = payload["compound_catalog"]["entries"]
                if problem == "duplicate_id":
                    entries.append(dict(entries[0]))
                elif problem == "foreign_image":
                    entries[0]["structure_id"] = "unowned-original"
                elif problem == "foreign_alias":
                    entries[0]["additional_sources"][0]["cpd"] = "Compound 8"
                else:
                    entries[0]["visible_label_candidates"] = None
                path.write_text(json.dumps(payload))
                with self.assertRaises(WebError) as rejected:
                    self.service.refresh(self.project.id)
                self.assertEqual(rejected.exception.code, "invalid_compound_catalog")

    def test_historical_review_does_not_run_current_semantic_proof_algorithms(self):
        _, payload = self.old_sources()
        structures = json.loads((self.run / "structures/metadata.json").read_text())[
            "structures"
        ]
        with (
            patch(
                "patent_sar_extractor.core.catalog_reader.annotate_binding_accuracy",
                side_effect=AssertionError("no current proof replay for history"),
            ),
            patch(
                "patent_sar_extractor.core.catalog_reader.annotate_source_binding",
                side_effect=AssertionError("no current proof replay for history"),
            ),
        ):
            rows, aliases = read_compound_catalog(
                payload, structures, historical_review=True
            )
        self.assertEqual([row["cpd"] for row in rows], ["Compound 1", "Compound 8"])
        self.assertEqual(aliases, {"proved-reprint"})
        self.assertTrue(
            all(
                row["accuracy_status"] != "confirmed" and row["fail_closed"]
                for row in rows
            )
        )

    def test_unchanged_current_source_does_not_stale_manual_edits_for_history_upgrade(
        self,
    ):
        uniform_tests.UniformRecognitionTests.prepare(self)
        document = self.service.get_correction(self.project.id, "Compound 8")
        self.service.put_correction(
            self.project.id,
            "Compound 8",
            CorrectionRequest(
                expected_revision=document.revision,
                expected_source_fingerprint=document.source_fingerprint,
                fields=EditableFields(
                    **{
                        **document.values.model_dump(),
                        "display_id": "Retained current review",
                    }
                ),
            ),
        )
        project = self.service.store.project(self.project.id)
        snapshot = json.loads(project["snapshot"])
        snapshot["raw_projection_layout"] = "compound-catalog-reprints-v2"
        snapshot.pop("historical_source_review_version", None)
        with self.service.store.connect(write=True) as connection:
            connection.execute(
                "UPDATE projects SET snapshot=? WHERE id=?",
                (json.dumps(snapshot), self.project.id),
            )
        current = self.service.get_correction(self.project.id, "Compound 8")
        self.assertFalse(current.stale)
        self.assertEqual(current.values.display_id, "Retained current review")
        self.assertEqual(current.revision, 1)

    def test_old_cached_history_is_rebuilt_without_retaining_current_chemistry(self):
        self.old_sources()
        project = self.service.store.project(self.project.id)
        snapshot = json.loads(project["snapshot"])
        snapshot.update(
            is_historical=True, raw_projection_layout="compound-catalog-reprints-v2"
        )
        snapshot.pop("historical_source_review_version", None)
        with self.service.store.connect(write=True) as connection:
            connection.execute(
                "UPDATE projects SET snapshot=? WHERE id=?",
                (json.dumps(snapshot), self.project.id),
            )
        self.service.project(self.project.id)
        current = json.loads(self.service.store.project(self.project.id)["snapshot"])
        self.assertEqual(current["historical_source_review_version"], 1)
        first = self.service.results(self.project.id).items[0]
        self.assertIsNone(first.smiles)
        self.assertEqual(first.recognition.status, "unavailable")

    def test_old_schema_with_parseable_proof_cannot_schedule_or_revive_current_chemistry(
        self,
    ):
        path, payload, _ = uniform_tests.UniformRecognitionTests.prepare(self)
        payload["schema"]["version"] -= 1
        path.write_text(json.dumps(payload))
        self.service.refresh(self.project.id)
        project = self.service.store.project(self.project.id)
        rows = {row["id"]: row for row in self.service.result_rows(self.project.id)}
        compounds = self.service.result_queries.effective_compounds(self.project.id)
        self.assertTrue(
            all(row.recognition.status == "unavailable" for row in compounds)
        )
        self.assertTrue(all(row.smiles is None for row in compounds))
        self.assertEqual(completion_inputs(project, rows, compounds), [])
        binding, _ = recognition_sources(project, "Compound 1")
        self.assertIsNone(binding)


if __name__ == "__main__":
    unittest.main()
