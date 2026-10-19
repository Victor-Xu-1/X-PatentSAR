"""Complete source retention, independent from original formal activity QA."""

from __future__ import annotations

import csv
import io
import json
import unittest
from collections import Counter

from test_prediction_support import PredictionFixture

from patent_sar_extractor.web.correction_models import CorrectionRequest
from patent_sar_extractor.web.errors import WebError
from patent_sar_extractor.web.exports import export_json
from patent_sar_extractor.web.sar.project_inputs import project_inputs


class StructureCorpusTests(PredictionFixture, unittest.TestCase):
    def add_source(self, *, unavailable=False, consistent_inventory=True):
        path = self.run / "structures/metadata.json"
        payload = json.loads(path.read_text())
        row = {**payload["structures"][0], "structure_id": "unassociated-observation"}
        if unavailable:
            row.pop("image_path", None)
            row.pop("bbox_pdf", None)
        payload["structures"].append(row)
        if consistent_inventory:
            # This fixture declares a second controlled observation. Keep its
            # full-page count envelope consistent; no real artifact is edited.
            payload["total_structures"] = len(payload["structures"])
            counts = Counter(item["page_no"] for item in payload["structures"])
            for page in payload["source_inventory"]["pages"]:
                page["candidates"] = counts[page["page_no"]]
        path.write_text(json.dumps(payload))
        self.service.refresh(self.project.id)
        return self.service.results(self.project.id)

    def test_generated_label_is_absent_from_identifier_choices_and_exports(self):
        row = next(
            item
            for item in self.add_source().items
            if item.record_kind == "structure_only"
        )
        files = {
            path: path.read_bytes() for path in self.run.rglob("*") if path.is_file()
        }
        prefix = f"/api/v1/projects/{self.project.id}"
        with self.client() as client:
            rows = client.get(prefix + "/results").json()["items"]
            actual = next(item for item in rows if item["id"] == row.id)
            self.assertNotIn("identifier_label", actual)
            self.assertEqual(actual["display_id"], row.display_id)
            self.assertEqual(actual["structure_id"], row.structure_id)
            choices = client.get(
                prefix + "/filter-values", params={"column": "compound"}
            )
            self.assertEqual(choices.status_code, 200, choices.text)
            self.assertNotIn(
                row.display_id, {item["value"] for item in choices.json()["items"]}
            )
            response = client.post(
                prefix + "/export", json={"format": "json", "compound_ids": [row.id]}
            )
            self.assertEqual(response.status_code, 200, response.text)
            exported = response.json()["items"][0]
            self.assertNotIn("identifier_label", exported)
            self.assertEqual(exported["display_id"], row.display_id)
            self.assertTrue(response.json()["review_only"])
            csv_response = client.post(
                prefix + "/export", json={"format": "csv", "compound_ids": [row.id]}
            )
            self.assertEqual(csv_response.status_code, 200, csv_response.text)
            csv_row = next(
                csv.DictReader(io.StringIO(csv_response.content.decode("utf-8-sig")))
            )
            self.assertEqual(csv_row["identifier_label"], "")
            self.assertEqual(csv_row["compound_id"], row.id)
            self.assertEqual(csv_row["display_id"], row.display_id)
        self.assertEqual({path: path.read_bytes() for path in files}, files)

    def test_effective_label_origin_survives_graph_edits_stale_renames_and_reset(self):
        row = next(
            item
            for item in self.add_source().items
            if item.record_kind == "structure_only"
        )
        self.service.corrections.on_save = None
        files = {
            path: path.read_bytes() for path in self.run.rglob("*") if path.is_file()
        }

        def save(**changes):
            document = self.service.get_correction(self.project.id, row.id)
            return self.service.put_correction(
                self.project.id,
                row.id,
                CorrectionRequest(
                    expected_revision=document.revision,
                    expected_source_fingerprint=document.source_fingerprint,
                    fields={**document.values.model_dump(), **changes},
                ),
            )

        def current():
            imported = project_inputs(self.service, self.project.id)[0]
            self.assertNotIn(row.id, {item.source_compound_id for item in imported})
            return next(
                item
                for item in self.service.compounds(self.project.id)
                if item.id == row.id
            )

        save(smiles="CCO")
        graph_edit = current()
        self.assertTrue(graph_edit.correction.has_changes)
        self.assertFalse(graph_edit.correction.identifier_changed)
        self.assertIsNone(graph_edit.identifier_label)
        self.assertEqual(graph_edit.display_id, row.display_id)
        save(display_id="Reviewed original 008A")
        renamed = current()
        self.assertTrue(renamed.correction.identifier_changed)
        self.assertEqual(renamed.identifier_label, "Reviewed original 008A")
        self.service.refresh(self.project.id)
        stale = current()
        self.assertTrue(stale.correction.stale)
        self.assertTrue(stale.correction.has_changes)
        self.assertFalse(stale.correction.identifier_changed)
        self.assertEqual(stale.display_id, row.display_id)
        self.assertIsNone(stale.identifier_label)
        document = self.service.get_correction(self.project.id, row.id)
        save(**document.original.model_dump())
        reset = current()
        self.assertFalse(reset.correction.has_changes)
        self.assertFalse(reset.correction.identifier_changed)
        self.assertIsNone(reset.identifier_label)
        self.assertEqual({path: path.read_bytes() for path in files}, files)

    def test_missing_candidate_inventory_is_rejected_without_discarding_observation(
        self,
    ):
        result = self.add_source(consistent_inventory=False)
        self.assertEqual(result.total, 2)
        acceptance = self.service.project(self.project.id).acceptance
        self.assertEqual(acceptance.state, "failed")
        self.assertTrue(any("candidate count" in error for error in acceptance.errors))

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
        self.assertEqual(row.recognition.status, "unavailable")
        self.assertEqual(row.recognition.quality_flag, "unassigned_source_unverified")
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
            exported["formal_acceptance_scope"],
            "proved_printed_identifier_structure_corpus",
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
            ("bindings", ()),
            ("smiles", ("records",)),
        ):
            path = self.run / ARTIFACTS[name][0]
            payload = json.loads(path.read_text())
            for key in keys:
                payload[key] = []
            if name == "bindings":
                payload["compound_catalog"].update(
                    entries=[], numbered_compounds=0, source_observations=0
                )
            path.write_text(json.dumps(payload))
        self.service.refresh(self.project.id)
        result = self.service.results(self.project.id)
        self.assertEqual(result.total, 1)
        self.assertEqual(result.items[0].record_kind, "structure_only")
        self.assertEqual(result.items[0].activities, [])
        self.assertTrue(result.items[0].structure_image_url)
