"""Value-to-original-cell focus; local adapter fixtures are not extraction claims."""

from __future__ import annotations

import copy
import hashlib
import json
import unittest

import fitz
from test_web_support import WebFixture, artifact_run

from patent_sar_extractor.web.service import import_run


def evidence(value="0.15", bounds=None, *, owner="1", geometry_space=None):
    source = {
        "page_no": 1,
        "target": "Cereblon",
        "assay": "HTRF",
        "table_id": "Table 13",
        "cells": [
            {"field": "compound_id", "value": owner, "bbox": [10, 50, 40, 70]},
            {"field": "Ratio", "value": value, "bbox": bounds or [40, 50, 100, 70]},
            {"field": "Grade", "value": "+++", "bbox": [100, 50, 160, 70]},
        ],
    }
    if geometry_space is not None:
        source["geometry_space"] = geometry_space
    return source


class ActivityFocusTests(WebFixture, unittest.TestCase):
    def prepare(self, *, sources=None, rotation=0):
        pdf = self.root / "focus-original.pdf"
        with fitz.open() as doc:
            p = doc.new_page(width=300, height=200)
            p.insert_text((45, 65), "0.15")
            p.insert_text((105, 65), "+++")
            p.set_rotation(rotation)
            doc.save(pdf)
        run = artifact_run(self.root / "focus", pdf, rows=1)
        activity = run / "activity/activity_data.json"
        data = json.loads(activity.read_text())
        data["rows"] = [
            {
                "cpd": "Compound 1",
                "page_no": 1,
                "target": "Cereblon",
                "assay": "HTRF",
                "activity_values": {"Ratio": "0.15", "Grade": "+++"},
                "activity_sources": sources if sources is not None else [evidence()],
            }
        ]
        activity.write_text(json.dumps(data))
        self.immutable = {
            p: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in run.rglob("*")
            if p.is_file()
        }
        project = import_run(self.state, run, pdf_path=pdf)
        return f"/api/v1/projects/{project.id}"

    def selected(self, client, prefix, *, metric="Ratio"):
        response = client.get(prefix + "/results")
        self.assertEqual(response.status_code, 200, response.text)
        row = response.json()["items"][0]
        index = next(i for i, a in enumerate(row["activities"]) if a["name"] == metric)
        self.assertEqual(len(row["activity_source_keys"]), len(row["activities"]))
        return row, row["activity_source_keys"][index]

    def focus(self, client, prefix, row, key, *, page=1):
        return client.get(
            prefix + f"/pages/{page}",
            params={"focus_compound": row["id"], "focus_activity": key},
        )

    def test_exact_value_cell_and_same_page_other_metric_are_distinct_and_immutable(
        self,
    ):
        prefix = self.prepare()
        with self.client() as client:
            row, key = self.selected(client, prefix)
            response = self.focus(client, prefix, row, key)
            self.assertEqual(response.status_code, 200, response.text)
            focus = response.json()["activity_focus"]
            self.assertEqual(focus["status"], "located")
            self.assertEqual(focus["boxes"], [[40, 50, 100, 70]])
            self.assertEqual(focus["activity_key"], key)
            _, other = self.selected(client, prefix, metric="Grade")
            self.assertNotEqual(key, other)
            self.assertEqual(
                self.focus(client, prefix, row, other).json()["activity_focus"][
                    "boxes"
                ],
                [[100, 50, 160, 70]],
            )
            self.assertEqual(
                self.focus(client, prefix, row, key).json()["activity_focus"], focus
            )
            self.assertNotIn("activity_focus", client.get(prefix + "/pages/1").json())
        self.assertEqual(
            self.immutable,
            {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in self.immutable},
        )

    def test_missing_geometry_and_wrong_compound_proof_do_not_invent_boxes(self):
        sources = [evidence(owner="2")]
        prefix = self.prepare(sources=sources)
        with self.client() as client:
            row, key = self.selected(client, prefix)
            result = self.focus(client, prefix, row, key)
            self.assertEqual(result.status_code, 200, result.text)
            focus = result.json()["activity_focus"]
            self.assertEqual(focus["status"], "page_only")
            self.assertEqual(focus["boxes"], [])
            self.assertTrue(focus["message"])

    def test_missing_cell_box_preserves_page_only(self):
        source = evidence()
        source["cells"][1].pop("bbox")
        prefix = self.prepare(sources=[source])
        with self.client() as client:
            row, key = self.selected(client, prefix)
            self.assertEqual(
                self.focus(client, prefix, row, key).json()["activity_focus"]["boxes"],
                [],
            )

    def test_repeated_valid_observations_keep_distinct_boxes_not_whole_table(self):
        prefix = self.prepare(
            sources=[evidence(), evidence(bounds=[40, 80, 100, 100]), evidence()]
        )
        with self.client() as client:
            row, key = self.selected(client, prefix)
            self.assertEqual(
                self.focus(client, prefix, row, key).json()["activity_focus"]["boxes"],
                [[40, 50, 100, 70], [40, 80, 100, 100]],
            )

    def test_selection_rejects_stale_key_and_partial_or_malformed_parameters(self):
        prefix = self.prepare()
        with self.client() as client:
            row, key = self.selected(client, prefix)
            self.assertEqual(self.focus(client, prefix, row, "f" * 64).status_code, 409)
            for params in (
                {"focus_compound": row["id"]},
                {"focus_activity": key},
                {"focus_compound": row["id"], "focus_activity": "not-a-key"},
            ):
                self.assertEqual(
                    client.get(prefix + "/pages/1", params=params).status_code, 422
                )
            self.assertEqual(
                self.focus(client, prefix, {"id": "Foreign"}, key).status_code, 404
            )

    def test_manual_value_revision_stales_old_focus_without_borrowing_other_evidence(
        self,
    ):
        prefix = self.prepare()
        with self.client() as client:
            row, key = self.selected(client, prefix)
            path = prefix + "/structures/Compound%201/correction"
            before = client.get(path).json()
            fields = copy.deepcopy(before["values"])
            fields["activities"][0]["value"] = "99"
            response = client.put(
                path,
                json={
                    "expected_revision": before["revision"],
                    "expected_source_fingerprint": before["source_fingerprint"],
                    "fields": fields,
                },
            )
            self.assertEqual(response.status_code, 200, response.text)
            changed, changed_key = self.selected(client, prefix)
            self.assertNotEqual(changed_key, key)
            self.assertEqual(self.focus(client, prefix, row, key).status_code, 409)
            self.assertEqual(
                self.focus(client, prefix, changed, changed_key).json()[
                    "activity_focus"
                ]["status"],
                "page_only",
            )
            self.assertEqual(
                client.get(path).json()["source_fingerprint"],
                before["source_fingerprint"],
            )

    def test_out_of_page_cell_coordinates_fail_instead_of_clipping_a_false_focus(self):
        prefix = self.prepare(sources=[evidence(bounds=[280, 50, 340, 70])])
        with self.client() as client:
            row, key = self.selected(client, prefix)
            self.assertEqual(self.focus(client, prefix, row, key).status_code, 422)

    def test_explicit_unrotated_coordinates_transform_once(self):
        prefix = self.prepare(
            sources=[evidence(geometry_space="unrotated")], rotation=90
        )
        with self.client() as client:
            row, key = self.selected(client, prefix)
            result = self.focus(client, prefix, row, key)
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(
                result.json()["activity_focus"]["boxes"], [[130, 40, 150, 100]]
            )
            self.assertEqual(
                (result.json()["width"], result.json()["height"]), (200, 300)
            )

    def test_unknown_rotated_coordinate_orientation_does_not_guess(self):
        prefix = self.prepare(rotation=90)
        with self.client() as client:
            row, key = self.selected(client, prefix)
            self.assertEqual(
                self.focus(client, prefix, row, key).json()["activity_focus"]["status"],
                "page_only",
            )

    def test_result_keys_are_read_metadata_not_raw_rows_or_export_mutations(self):
        prefix = self.prepare()
        with self.client() as client:
            _row, key = self.selected(client, prefix)
            self.assertEqual(len(key), 64)
            raw = client.get(prefix + "/structures/Compound%201/correction").json()
            self.assertFalse(
                any(
                    "activity_source_keys" in activity
                    for activity in raw["original"]["activities"]
                )
            )
            exported = client.post(
                prefix + "/export", json={"format": "json", "compound_ids": []}
            ).json()
            self.assertNotIn("activity_source_keys", exported["items"][0])

    def test_focus_count_limit_is_rejected_before_rendering_excessive_boxes(self):
        source = evidence()
        source["cells"] = [source["cells"][0]] + [
            {
                "field": "Ratio",
                "value": "0.15",
                "bbox": [2 * index + 1, 50, 2 * index + 2, 70],
            }
            for index in range(81)
        ]
        prefix = self.prepare(sources=[source])
        with self.client() as client:
            row, key = self.selected(client, prefix)
            result = self.focus(client, prefix, row, key)
            self.assertEqual(result.status_code, 422, result.text)
            self.assertIn("activity_focus_limit", result.text)


if __name__ == "__main__":
    unittest.main()
