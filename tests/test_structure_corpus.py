"""Complete source retention, independent from original formal activity QA."""

from __future__ import annotations

import json
import unittest

from test_prediction_support import PredictionFixture

from patent_sar_extractor.web.correction_models import CorrectionRequest
from patent_sar_extractor.web.errors import WebError
from patent_sar_extractor.web.exports import export_json


class StructureCorpusTests(PredictionFixture, unittest.TestCase):
    def add_source(self, *, unavailable=False):
        path = self.run / "structures/metadata.json"
        payload = json.loads(path.read_text())
        row = {**payload["structures"][0], "structure_id": "unassociated-observation"}
        if unavailable:
            row.pop("image_path", None)
            row.pop("bbox_pdf", None)
        payload["structures"].append(row)
        path.write_text(json.dumps(payload))
        self.service.refresh(self.project.id)
        return self.service.results(self.project.id)

    def test_actual_structure_with_no_activity_is_retained_and_not_called_inactive(
        self,
    ):
        before = self.service.project(self.project.id).acceptance
        result = self.add_source()
        self.assertEqual(result.total, 2)
        row = next(
            item for item in result.items if item.record_kind == "structure_only"
        )
        self.assertEqual(row.activities, [])
        self.assertIsNone(row.smiles)
        self.assertEqual(row.recognition.status, "not_run")
        self.assertIn("编号待确认", row.display_id)
        self.assertNotIn("Compound", row.display_id)
        self.assertEqual(row.confidence.level, "review")
        self.assertIsNone(row.confidence.score)
        self.assertEqual(row.source.page, 1)
        self.assertTrue(row.structure_image_url)
        self.assertEqual(row.admet.status, "unavailable")
        self.assertEqual(row.admet.properties, [])
        current = self.service.project(self.project.id)
        self.assertEqual(current.summary.structure_only, 1)
        self.assertEqual(current.acceptance, before)
        identifier = row.id
        self.service.refresh(self.project.id)
        self.assertEqual(
            next(
                item.id
                for item in self.service.results(self.project.id).items
                if item.record_kind == "structure_only"
            ),
            identifier,
        )

    def test_missing_crop_is_explicit_but_observation_is_not_discarded(self):
        result = self.add_source(unavailable=True)
        row = next(
            item for item in result.items if item.record_kind == "structure_only"
        )
        self.assertIsNone(row.structure_image_url)
        self.assertIn("image_unavailable", row.flags)
        self.assertEqual(result.total, 2)

    def test_activity_rows_outside_formal_target_list_are_retained_separately(self):
        # Use the authoritative artifact route instead of assuming a producer filename.
        from patent_sar_extractor.web.acceptance import ARTIFACTS

        path = self.run / ARTIFACTS["activity"][0]
        payload = json.loads(path.read_text())
        payload["rows"].append(
            {
                "cpd": "Additional measured row",
                "activity_values": {"grade": "++"},
                "page_no": 1,
            }
        )
        path.write_text(json.dumps(payload))
        self.service.refresh(self.project.id)
        result = self.service.results(self.project.id)
        row = next(
            item for item in result.items if item.id == "Additional measured row"
        )
        self.assertEqual(row.record_kind, "activity_only")
        self.assertEqual(row.activities[0].value, "++")
        self.assertIsNone(row.structure_image_url)
        self.assertEqual(self.service.project(self.project.id).summary.activity_only, 1)

    def test_structure_only_source_supports_editing_and_export_without_rewriting_artifacts(
        self,
    ):
        row = next(
            item
            for item in self.add_source().items
            if item.record_kind == "structure_only"
        )
        files = {
            path: path.read_bytes() for path in self.run.rglob("*") if path.is_file()
        }
        original = self.service.get_correction(self.project.id, row.id)
        self.service.put_correction(
            self.project.id,
            row.id,
            CorrectionRequest(
                expected_revision=0,
                expected_source_fingerprint=original.source_fingerprint,
                fields={
                    **original.values.model_dump(),
                    "display_id": "Reviewed source",
                    "smiles": "CCO",
                },
            ),
        )
        effective = self.service.compounds(self.project.id)
        changed = next(item for item in effective if item.id == row.id)
        self.assertEqual(changed.smiles, "CCO")
        self.assertEqual(changed.activities, [])
        self.assertTrue(changed.redraw_image_url)
        self.assertEqual({path: path.read_bytes() for path in files}, files)
        exported = json.loads(
            b"".join(export_json(self.service.project(self.project.id), effective))
        )
        self.assertTrue(exported["review_only"])
        self.assertEqual(exported["structure_only"], 1)
        self.assertEqual(
            exported["formal_acceptance_scope"], "original_activity_association_only"
        )

    def test_duplicate_structure_ids_do_not_silently_choose_or_drop_an_observation(
        self,
    ):
        path = self.run / "structures/metadata.json"
        payload = json.loads(path.read_text())
        payload["structures"].append(dict(payload["structures"][0]))
        path.write_text(json.dumps(payload))
        with self.assertRaises(WebError) as error:
            self.service.refresh(self.project.id)
        self.assertEqual(error.exception.code, "ambiguous_structure")

    def test_zero_activity_still_projects_real_structure_observations(self):
        from patent_sar_extractor.web.acceptance import ARTIFACTS

        for name, keys in (
            ("activity", ("rows", "active_cpds")),
            ("bindings", ("final_bindings",)),
            ("smiles", ("records",)),
        ):
            path = self.run / ARTIFACTS[name][0]
            payload = json.loads(path.read_text())
            for key in keys:
                payload[key] = []
            path.write_text(json.dumps(payload))
        self.service.refresh(self.project.id)
        result = self.service.results(self.project.id)
        self.assertEqual(result.total, 1)
        self.assertEqual(result.items[0].record_kind, "structure_only")
        self.assertEqual(result.items[0].activities, [])
        self.assertTrue(result.items[0].structure_image_url)
