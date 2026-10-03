"""Per-measurement provenance; controlled fixtures never prove core extraction."""

from __future__ import annotations

import copy
import csv
import hashlib
import io
import json
import unittest

import fitz
from test_web_support import WebFixture, artifact_run

from patent_sar_extractor.web.artifacts import _activities
from patent_sar_extractor.web.errors import WebError
from patent_sar_extractor.web.service import import_run


def cell(field, value):
    return {
        "field": field,
        "value": value,
        "bbox": [10, 10, 40, 30],
        "observations": [{"method": "native_cell", "text": str(value)}],
    }


def source(page, target, assay, cells):
    return {
        "page_no": page,
        "table_id": f"Table {page}",
        "target": target,
        "assay": assay,
        "cell_line": "KP4" if assay == "Western blot" else None,
        "row": 0,
        "pair": 0,
        "cells": [cell("compound_id", "1"), *cells],
    }


def multi_assay_row():
    return {
        "cpd": "Compound 1",
        "page_no": 1,
        "target": "Legacy target",
        "assay": "Legacy assay",
        "activity_values": {
            "Cereblon HTRF ratio": "0.09",
            "Cereblon HTRF grade": "+++",
            "KP4 HuR degradation grade": "A",
            "Anti-proliferation activity grade": "+++",
        },
        "activity_sources": [
            source(
                1,
                "Cereblon",
                "HTRF",
                [
                    cell("Cereblon HTRF ratio", "0.09"),
                    cell("Cereblon HTRF grade", "+++"),
                ],
            ),
            source(2, "HuR", "Western blot", [cell("KP4 HuR degradation grade", "A")]),
            source(
                3,
                None,
                "Anti-proliferation",
                [cell("Anti-proliferation activity grade", "+++")],
            ),
        ],
    }


class ActivitySourceTests(unittest.TestCase):
    def test_multi_assay_metrics_keep_their_own_pages_targets_and_assays(self):
        items = {item.name: item for item in _activities(multi_assay_row())}
        self.assertEqual(
            (
                items["Cereblon HTRF ratio"].page,
                items["Cereblon HTRF ratio"].target,
                items["Cereblon HTRF ratio"].assay,
            ),
            (1, "Cereblon", "HTRF"),
        )
        self.assertEqual(
            (
                items["KP4 HuR degradation grade"].page,
                items["KP4 HuR degradation grade"].target,
                items["KP4 HuR degradation grade"].assay,
            ),
            (2, "HuR", "Western blot"),
        )
        self.assertEqual(
            (
                items["Anti-proliferation activity grade"].page,
                items["Anti-proliferation activity grade"].target,
                items["Anti-proliferation activity grade"].assay,
            ),
            (3, None, "Anti-proliferation"),
        )
        self.assertEqual(items["Cereblon HTRF grade"].page, 1)
        self.assertTrue(all(item.unit is None for item in items.values()))

    def test_source_matching_requires_exact_field_and_untruncated_original_value(self):
        for field, value in (
            ("cereblon HTRF ratio", "0.09"),
            ("Cereblon HTRF ratio", "0.090"),
        ):
            row = multi_assay_row()
            row["activity_sources"][0]["cells"] = [cell(field, value)]
            item = next(
                item for item in _activities(row) if item.name == "Cereblon HTRF ratio"
            )
            self.assertEqual(
                (item.target, item.assay), ("Legacy target", "Legacy assay")
            )
        row = multi_assay_row()
        row["activity_values"] = {"long value": "x" * 1000 + "tail"}
        row["activity_sources"] = [
            source(2, "Wrong target", "Wrong assay", [cell("long value", "x" * 1000)])
        ]
        self.assertEqual(_activities(row)[0].target, "Legacy target")

    def test_old_missing_empty_or_unmatched_evidence_retains_row_metadata(self):
        for evidence in (
            None,
            [],
            [source(3, None, "Other assay", [cell("unrelated", "+++")])],
        ):
            row = multi_assay_row()
            row["activity_sources"] = evidence
            items = _activities(row)
            self.assertTrue(
                all(
                    (item.page, item.target, item.assay)
                    == (1, "Legacy target", "Legacy assay")
                    for item in items
                )
            )
        row.pop("activity_sources")
        self.assertEqual(_activities(row)[0].assay, "Legacy assay")

    def test_duplicate_source_context_is_deduplicated_but_distinct_contexts_are_retained(
        self,
    ):
        row = multi_assay_row()
        row["activity_sources"].append(copy.deepcopy(row["activity_sources"][0]))
        row["activity_sources"].append(
            source(
                3,
                "Cereblon",
                "Separate observed assay",
                [cell("Cereblon HTRF ratio", "0.09")],
            )
        )
        items = [
            item for item in _activities(row) if item.name == "Cereblon HTRF ratio"
        ]
        self.assertEqual(
            [(item.page, item.assay) for item in items],
            [(1, "HTRF"), (3, "Separate observed assay")],
        )
        self.assertEqual([item.value for item in items], ["0.09", "0.09"])

    def test_cell_line_data_uses_the_same_evidence_lookup_without_inventing_units(self):
        row = multi_assay_row()
        row["cell_line_data"] = {"DC50 (nM)": "<10"}
        row["activity_sources"].append(
            source(2, "HuR", "Measured cell assay", [cell("DC50 (nM)", "<10")])
        )
        item = next(item for item in _activities(row) if item.name == "DC50 (nM)")
        self.assertEqual(
            (item.value, item.unit, item.page, item.target, item.assay),
            ("<10", "nM", 2, "HuR", "Measured cell assay"),
        )

    def test_omitted_source_metadata_retains_existing_fields_without_guessing(self):
        row = multi_assay_row()
        for evidence in row["activity_sources"]:
            evidence.pop("target")
            evidence.pop("assay")
        item = next(
            item
            for item in _activities(row)
            if item.name == "KP4 HuR degradation grade"
        )
        self.assertEqual(
            (item.page, item.target, item.assay), (2, "Legacy target", "Legacy assay")
        )

    def test_source_page_is_bounded_by_the_original_when_available(self):
        with self.assertRaises(WebError) as error:
            _activities(multi_assay_row(), page_count=2)
        self.assertEqual(error.exception.status, 422)
        self.assertEqual(len(_activities(multi_assay_row(), page_count=3)), 4)

    def test_malformed_and_over_limit_provenance_is_rejected_without_sensitive_errors(
        self,
    ):
        valid = multi_assay_row()["activity_sources"][0]
        bad = [
            {},
            True,
            [None],
            [valid] * 501,
            [{**valid, "cells": "invalid"}],
            [{**valid, "target": {"private_path": "/private/file"}}],
            [{**valid, "assay": False}],
            [{**valid, "page_no": True}],
            [{**valid, "page_no": False}],
            [{**valid, "page_no": 0}],
            [{**valid, "page_no": 0.0}],
            [{**valid, "page_no": "not a page"}],
            [{**valid, "cells": [cell("Cereblon HTRF ratio", True)]}],
            [{**valid, "cells": [cell("f" * 301, "0.09")]}],
            [{**valid, "cells": [{**cell("x", "1"), "bbox": [0, 0, float("nan"), 1]}]}],
            [{**valid, "cells": [{**cell("x", "1"), "observations": "invalid"}]}],
            [{**valid, "cells": [cell("x", "1")] * 501}],
            [{**valid, "cells": [cell("x", "1")] * 500}] * 5,
            [{**valid, "cells": [{**cell("x", "1"), "observations": [{}] * 21}]}],
            [{**valid, "row": -1}],
        ]
        for evidence in bad:
            with self.subTest(evidence_type=type(evidence).__name__):
                row = multi_assay_row()
                row["activity_sources"] = evidence
                with self.assertRaises(WebError) as error:
                    _activities(row)
                self.assertEqual(error.exception.status, 422)
                self.assertNotIn("/private", str(error.exception))


class ActivitySourceAPITests(WebFixture, unittest.TestCase):
    def test_results_filters_exports_and_evidence_summary_preserve_assay_provenance(
        self,
    ):
        pdf = self.root / "three-page-original.pdf"
        with fitz.open() as document:
            for page in range(3):
                document.new_page(width=300, height=200).insert_text(
                    (20, 25), f"Controlled assay source page {page + 1}"
                )
            document.save(pdf)
        run = artifact_run(self.root / "multi-assay", pdf, rows=1, accepted=False)
        for path in (
            run / "page_classification/page_classification.json",
            run / "page_classification/page_ocr_cache.json",
        ):
            payload = json.loads(path.read_text())
            (payload["metadata"] if "metadata" in payload else payload)[
                "page_count"
            ] = 3
            path.write_text(json.dumps(payload))
        path = run / "activity/activity_data.json"
        payload = json.loads(path.read_text())
        payload["rows"] = [multi_assay_row()]
        path.write_text(json.dumps(payload))
        before = {
            p: hashlib.sha256(p.read_bytes()).hexdigest() for p in run.rglob("*.json")
        }
        imported = import_run(self.state, run, pdf_path=pdf)
        with self.client() as client:
            prefix = f"/api/v1/projects/{imported.id}"
            response = client.get(prefix + "/results")
            self.assertEqual(response.status_code, 200, response.text)
            data = response.json()
            self.assertEqual(data["targets"], ["Cereblon", "HuR"])
            items = {item["name"]: item for item in data["items"][0]["activities"]}
            self.assertEqual(items["KP4 HuR degradation grade"]["page"], 2)
            self.assertIsNone(items["Anti-proliferation activity grade"]["target"])
            self.assertEqual(
                client.get(prefix + "/results?target=HuR").json()["total"], 1
            )
            self.assertEqual(
                client.get(prefix + "/results?target=Legacy%20target").json()["total"],
                0,
            )
            exported = client.post(
                prefix + "/export", json={"format": "json", "compound_ids": []}
            ).json()
            self.assertEqual(
                exported["items"][0]["activities"], data["items"][0]["activities"]
            )
            exported_csv = client.post(
                prefix + "/export", json={"format": "csv", "compound_ids": []}
            )
            records = {
                row["metric"]: row
                for row in csv.DictReader(
                    io.StringIO(exported_csv.content.decode("utf-8-sig"))
                )
            }
            self.assertEqual(
                (
                    records["KP4 HuR degradation grade"]["activity_page"],
                    records["KP4 HuR degradation grade"]["target"],
                    records["KP4 HuR degradation grade"]["assay"],
                ),
                ("2", "HuR", "Western blot"),
            )
            summary = client.get(prefix + "/evidence-summary").json()
            self.assertEqual(summary["source_pages"], [1, 2, 3])
            self.assertEqual(
                {item["name"]: item["rows"] for item in summary["targets"]},
                {"Cereblon": 2, "HuR": 1},
            )
            self.assertEqual(summary["acceptance"]["state"], "failed")
        self.assertEqual(
            before, {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in before}
        )
