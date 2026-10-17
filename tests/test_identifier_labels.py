"""Patent labels change presentation only, never identity or source evidence."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import unittest
from pathlib import Path

from pydantic import ValidationError
from test_web_support import WebFixture, artifact_run

from patent_sar_extractor.web.identifier_labels import identifier_label
from patent_sar_extractor.web.models import Compound, CorrectionMetadata
from patent_sar_extractor.web.service import WorkspaceService, import_run
from patent_sar_extractor.web.table_queries import matches
from patent_sar_extractor.web.table_query_models import ColumnFilter


def compound(
    canonical: str, source: str | None = None, display: str | None = None
) -> Compound:
    return Compound(
        id=canonical,
        display_id=display or canonical,
        activities=[],
        source={"page": 1, "source_label": source},
        confidence={"level": "unknown", "reason": "Controlled identity fixture"},
    )


class IdentifierLabelTests(unittest.TestCase):
    def pending(self, *, structure_id="S0192", suffix=""):
        identity = "source-structure:" + "a" * 32 + suffix
        reference = structure_id or identity.rsplit(":", 1)[-1][-8:]
        return compound(identity, display=f"编号待确认 {reference}").model_copy(
            update={
                "structure_id": structure_id,
                "record_kind": "structure_only",
                "flags": ["unassociated_structure", "structure_number_unconfirmed"],
            }
        )

    def test_generated_source_reference_is_not_a_literal_patent_identifier(self):
        for structure_id, suffix in (("S0000", ""), (None, ""), (None, ":2")):
            with self.subTest(structure_id=structure_id, suffix=suffix):
                row = self.pending(structure_id=structure_id, suffix=suffix)
                before = row.model_dump()
                self.assertIsNone(identifier_label(row))
                self.assertEqual(row.model_dump(), before)

    def test_incomplete_generated_origin_and_literal_source_labels_are_preserved(self):
        row = self.pending()
        variants = (
            {"id": "Compound 001A"},
            {"id": "source-structure:" + "a" * 31},
            {"record_kind": "activity_only"},
            {"flags": ["unassociated_structure"]},
            {"structure_id": "S0193"},
            {"display_id": "编号待确认 User label"},
            {"source": row.source.model_copy(update={"source_label": row.display_id})},
        )
        for updates in variants:
            with self.subTest(updates=updates):
                original = row.model_copy(update=updates)
                self.assertEqual(identifier_label(original), original.display_id)

    def test_unknown_legacy_manual_change_cannot_be_mistaken_for_generated_copy(self):
        row = self.pending()
        row.correction = CorrectionMetadata(
            revision=1, stale=False, has_changes=True, updated_at="2026-10-01"
        )
        self.assertEqual(identifier_label(row), row.display_id)

    def test_only_a_proved_effective_nonrename_can_localize_a_changed_overlay(self):
        for renamed, expected in ((True, "编号待确认 S0192"), (False, None)):
            row = self.pending()
            row.correction = CorrectionMetadata(
                revision=1,
                stale=False,
                has_changes=True,
                updated_at="2026-10-01",
                identifier_changed=renamed,
            )
            self.assertEqual(identifier_label(row), expected)

    def test_effective_identifier_metadata_is_boolean_or_unknown_never_truthy_text(
        self,
    ):
        for invalid in ("false", 0, [], {}):
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                CorrectionMetadata(
                    revision=1,
                    stale=False,
                    has_changes=True,
                    updated_at="2026-10-01",
                    identifier_changed=invalid,
                )

    def test_exact_source_label_preserves_patent_prefix_digits_case_and_suffix(self):
        for canonical, source, expected in (
            ("Compound 1", "1", "1"),
            ("Compound 008a", "Example 008a", "Example 008a"),
            ("Compound I-03B", "化合物 I-03B", "化合物 I-03B"),
            ("Compound 8A", "8A.", "8A."),
            ("Compound 8B", "Cmpd 8B", "Cmpd 8B"),
            ("Compound BMS-001-2", "BMS-001-2", "BMS-001-2"),
            ("Compound 1", "2", "1"),
            ("Compound 8A", "8B", "8A"),
            ("Compound 1", None, "1"),
            ("编号待确认 S009", "9", "编号待确认 S009"),
            ("Ref 1", None, "Ref 1"),
            ("custom-key", "unproved text", "custom-key"),
        ):
            with self.subTest(canonical=canonical, source=source):
                row = compound(canonical, source)
                before = row.model_dump()
                self.assertEqual(identifier_label(row), expected)
                self.assertEqual(row.model_dump(), before)
        self.assertEqual(
            identifier_label(compound("Compound 1", "1", "User label")), "User label"
        )

    def test_legacy_filter_aliases_preserve_prefix_zeros_and_enantiomer_identity(self):
        row = compound("Compound I-008A", "I-008A")
        for op in ("eq", "in"):
            for value in ("I-008A", "Compound I-008A", "Example I-008A"):
                criterion = ColumnFilter(
                    column="compound",
                    op=op,
                    **({"value": value} if op == "eq" else {"values": [value]}),
                )
                self.assertTrue(matches(row, criterion))
            for value in ("I-8A", "008A", "I-008B"):
                criterion = ColumnFilter(
                    column="compound",
                    op=op,
                    **({"value": value} if op == "eq" else {"values": [value]}),
                )
                self.assertFalse(matches(row, criterion))


class IdentifierAPITests(WebFixture, unittest.TestCase):
    def test_real_results_choices_exports_and_correction_keep_stable_identity(self):
        run = artifact_run(self.root / "run", self.pdf)
        binding_path = run / "structure_bindings/bindings.json"
        binding = json.loads(binding_path.read_text())
        for records in (
            binding["final_bindings"],
            binding["compound_catalog"]["entries"],
        ):
            for row in records:
                row["authoritative_table_source_label"] = (
                    "Example " + row["cpd"].split()[-1]
                )
        binding_path.write_text(json.dumps(binding))
        original_files = {
            str(path): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in run.rglob("*")
            if path.is_file()
        }
        project = import_run(self.state, run, pdf_path=self.pdf)
        service = WorkspaceService(self.state)
        raw = service.store.compound(project.id, "Compound 1")
        endpoint = f"/api/v1/projects/{project.id}"
        with self.client() as client:
            client.app.state.workspace.corrections.on_save = None
            rows = client.get(endpoint + "/results").json()["items"]
            row = next(item for item in rows if item["id"] == "Compound 1")
            self.assertEqual(row["display_id"], "Compound 1")
            self.assertEqual(row["identifier_label"], "Example 1")
            for value in ("Example 1", "Compound 1", "1"):
                response = client.get(
                    endpoint + "/results",
                    params={
                        "column_filters": json.dumps(
                            [{"column": "compound", "op": "eq", "value": value}]
                        )
                    },
                )
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(
                    [item["id"] for item in response.json()["items"]], ["Compound 1"]
                )
            self.assertEqual(
                client.get(endpoint + "/results", params={"q": "Example 1"}).json()[
                    "total"
                ],
                1,
            )
            exported = client.post(
                endpoint + "/export",
                json={"format": "csv", "compound_ids": ["Compound 1"]},
            )
            self.assertEqual(exported.status_code, 200, exported.text)
            csv_row = next(
                csv.DictReader(io.StringIO(exported.content.decode("utf-8-sig")))
            )
            self.assertEqual(csv_row["compound_id"], "Compound 1")
            self.assertEqual(csv_row["identifier_label"], "Example 1")
            choices = client.get(
                endpoint + "/filter-values", params={"column": "compound"}
            )
            self.assertEqual(choices.status_code, 200, choices.text)
            self.assertEqual(
                {item["value"] for item in choices.json()["items"]},
                {"Example 1", "Example 2"},
            )
            correction_path = endpoint + "/structures/Compound%201/correction"
            first = client.get(correction_path).json()
            self.assertEqual(first["values"]["display_id"], "Compound 1")
            saved = client.put(
                correction_path,
                json={
                    "expected_revision": 0,
                    "expected_source_fingerprint": first["source_fingerprint"],
                    "fields": {**first["values"], "display_id": "Audited new label"},
                },
            )
            self.assertEqual(saved.status_code, 200, saved.text)
            current = client.get(
                endpoint + "/results", params={"q": "Audited new label"}
            ).json()["items"][0]
            self.assertEqual(current["id"], "Compound 1")
            self.assertEqual(current["identifier_label"], "Audited new label")
            self.assertEqual(
                client.get(correction_path).json()["source_fingerprint"],
                first["source_fingerprint"],
            )
        self.assertEqual(service.store.compound(project.id, "Compound 1"), raw)
        self.assertEqual(
            original_files,
            {
                path: hashlib.sha256(Path(path).read_bytes()).hexdigest()
                for path in original_files
            },
        )
