"""Initial source navigation is an explicit structure fact, not an activity guess."""

import json
import unittest
from unittest.mock import patch

from test_prediction_support import PredictionFixture

from patent_sar_extractor.web.correction_models import CorrectionRequest
from patent_sar_extractor.web.service import WorkspaceService


class FirstStructurePageTests(PredictionFixture, unittest.TestCase):
    def test_raw_projection_excludes_presentation_overlays_and_bootstraps_before_edit(
        self,
    ):
        raw = json.loads(
            self.service.store.compound(self.project.id, "Compound 1")["payload"]
        )
        self.assertNotIn("admet", raw)
        self.assertNotIn("correction", raw)
        with self.service.store.connect(write=True) as connection:
            project = self.service.store.project(self.project.id)
            snapshot = json.loads(project["snapshot"])
            snapshot.pop("raw_projection_layout")
            connection.execute(
                "UPDATE projects SET snapshot=? WHERE id=?",
                (json.dumps(snapshot), self.project.id),
            )
        document = self.service.get_correction(self.project.id, "Compound 1")
        request = CorrectionRequest(
            expected_revision=0,
            expected_source_fingerprint=document.source_fingerprint,
            fields={
                **document.values.model_dump(),
                "display_id": "Edit after bootstrap",
            },
        )
        self.assertEqual(
            self.service.put_correction(
                self.project.id, "Compound 1", request
            ).revision,
            1,
        )
        self.assertEqual(
            self.service.get_correction(
                self.project.id, "Compound 1"
            ).source_fingerprint,
            document.source_fingerprint,
        )

    def test_project_metadata_does_not_open_pdf_and_manual_activity_edits_do_not_change_it(
        self,
    ):
        document = self.service.get_correction(self.project.id, "Compound 1")
        activities = [
            {**a.model_dump(), "page": None} for a in document.values.activities
        ]
        request = CorrectionRequest(
            expected_revision=0,
            expected_source_fingerprint=document.source_fingerprint,
            fields={**document.values.model_dump(), "activities": activities},
        )
        self.service.put_correction(self.project.id, "Compound 1", request)
        with patch(
            "patent_sar_extractor.web.pdf.open_pdf",
            side_effect=AssertionError("Project metadata must not open PDF"),
        ):
            self.assertEqual(
                self.service.project(self.project.id).first_structure_page, 1
            )

    def test_missing_actual_structure_page_does_not_borrow_activity_fallback(self):
        for relative, key in (
            ("structure_bindings/bindings.json", "final_bindings"),
            ("structures/metadata.json", "structures"),
        ):
            path = self.run / relative
            payload = json.loads(path.read_text())
            for entry in payload[key]:
                entry["page_no"] = None
            path.write_text(json.dumps(payload))
        self.service.refresh(self.project.id)
        row = self.service.compounds(self.project.id)[0]
        self.assertEqual(row.activities[0].page, 1)
        self.assertEqual(row.source.page, 1)
        self.assertIsNone(self.service.project(self.project.id).first_structure_page)

    def test_old_projection_is_rebuilt_once_before_prediction_enqueue(self):
        with self.service.store.connect(write=True) as connection:
            project = self.service.store.project(self.project.id)
            snapshot = json.loads(project["snapshot"])
            snapshot.pop("first_structure_page")
            connection.execute(
                "UPDATE projects SET snapshot=? WHERE id=?",
                (json.dumps(snapshot), self.project.id),
            )
        rebuilt = self.service.project(self.project.id)
        self.assertEqual(rebuilt.first_structure_page, 1)
        stable = self.service.store.project(self.project.id)["snapshot"]
        self.assertEqual(
            WorkspaceService(self.state).project(self.project.id).first_structure_page,
            1,
        )
        self.assertEqual(
            self.service.store.project(self.project.id)["snapshot"], stable
        )
