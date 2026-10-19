"""Source-local metric/condition namespaces conserve original experimental rows."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from patent_sar_extractor.core.sar.study_contexts import context_catalog
from patent_sar_extractor.web.artifacts import _activities
from patent_sar_extractor.web.errors import WebError
from patent_sar_extractor.web.sar.csv_reader import preview
from patent_sar_extractor.web.sar.input_records import metric_key
from patent_sar_extractor.web.sar.observation_contexts import ObservationContexts
from patent_sar_extractor.web.sar.study_activity_view import prepare_activity
from tests.test_activity_source_scopes import source_row


class SARSourceContextTests(unittest.TestCase):
    def test_unsupported_or_boolean_input_versions_cannot_become_current_studies(self):
        for version in (True, 1, 9, None, "8"):
            with self.subTest(version=version), self.assertRaises(WebError):
                prepare_activity({"schema": version}, None)

    def test_native_export_roles_are_explicit_not_ambiguous_aliases(self):
        data = (
            b"review_only,acceptance_state,compound_id,display_id,identifier_label,smiles,metric,value,unit,source_page,activity_page,structure_molfile_json\n"
            b"True,failed,Compound 1,Example 001,001,CO,IC50,1,nM,7,12,\n"
        )
        observed = preview(data, "native.csv", "a" * 32)
        self.assertEqual(observed.suggested_id, "identifier_label")
        self.assertEqual(
            observed.mapping_defaults.columns["source_page_column"], "activity_page"
        )

    def test_same_value_does_not_duplicate_or_borrow_other_table_conditions(self):
        rows = [source_row(1), source_row(2)]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "activity").mkdir()
            path = root / "activity/activity_data.json"
            path.write_text(json.dumps({"rows": rows}))
            before = hashlib.sha256(path.read_bytes()).hexdigest()
            contexts = ObservationContexts(
                {
                    "run_root": str(root),
                    "sha256": "a" * 64,
                    "expected_sha256": "a" * 64,
                    "page_count": 5,
                }
            )
            molecules, metrics = [], []
            for row in rows:
                activity = _activities(row, page_count=5, document_sha256="a" * 64)[0]
                selected = contexts.contexts("1", activity)
                self.assertEqual(len(selected), 1)
                self.assertEqual(selected[0]["cell_line"], "HEK293")
                key = metric_key(
                    activity.name,
                    activity.unit,
                    activity.target,
                    activity.assay,
                    activity.source_scope,
                )
                metrics.append(
                    {
                        "id": key,
                        "name": activity.name,
                        "source_scope": activity.source_scope,
                        "source_table": activity.source_table,
                        "source_context_page": activity.source_context_page,
                    }
                )
                molecules.append(
                    {
                        "id": str(len(molecules)),
                        "observations": [
                            {
                                "metric_id": key,
                                "value": "1",
                                "unit": "nM",
                                "context": selected[0],
                            }
                        ],
                    }
                )
            catalog = context_catalog(molecules, metrics)
            self.assertEqual(len(catalog), 2)
            self.assertEqual(
                {c["source_table"] for c in catalog}, {"Table 1", "Table 2"}
            )
            self.assertNotEqual(catalog[0]["id"], catalog[1]["id"])
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)

    def test_legacy_or_csv_metric_identity_stays_byte_compatible(self):
        expected = hashlib.sha256(
            json.dumps(
                ["IC50", "nM", "T", "binding"],
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        self.assertEqual(metric_key("IC50", "nM", "T", "binding"), expected)
        self.assertNotEqual(
            metric_key("IC50", "nM", "T", "binding", "a" * 64), expected
        )
