"""Native CSV namespaces are preserved, bounded and never original acceptance."""

import csv
import io
import json
import unittest

from patent_sar_extractor.web.errors import WebError
from patent_sar_extractor.web.sar.csv_inputs import mapped_inputs
from patent_sar_extractor.web.sar.csv_scope import (
    native_conditions,
    native_scope_fields,
)
from patent_sar_extractor.web.sar.models import CSVMapping


def native_csv(*, second=None):
    first = {
        "review_only": "True",
        "acceptance_state": "failed",
        "compound_id": "internal",
        "identifier_label": "001B",
        "smiles": "CO",
        "metric": "IC50",
        "value": "<1",
        "unit": "nM",
        "source_page": "7",
        "activity_page": "12",
        "structure_molfile_json": "",
        "source_scope": "a" * 64,
        "source_table": "Table 2",
        "source_context_page": "11",
        "source_conditions_json": json.dumps(
            {"cell_line": "HEK293", "duration": "24 h"}
        ),
    }
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(first))
    writer.writeheader()
    writer.writerow(first)
    if second is not None:
        writer.writerow({**first, **second})
    return stream.getvalue().encode()


class NativeCSVSourceScopeTests(unittest.TestCase):
    def mapping(self):
        return CSVMapping(
            token="a" * 32,
            request_id="b" * 32,
            title="Generated",
            id_column="identifier_label",
            smiles_column="smiles",
            activity_columns=["value"],
            metric_column="metric",
            unit_column="unit",
            source_page_column="activity_page",
        )

    def test_native_graph_and_activity_pages_and_literal_identifier_are_distinct(self):
        molecules, metrics, count = mapped_inputs(native_csv(), self.mapping())
        self.assertEqual(count, 1)
        self.assertEqual(molecules[0].label, "001B")
        self.assertEqual(molecules[0].source_page, 7)
        item = molecules[0].observations[0]
        self.assertEqual(
            (item.source_page, item.value, item.source_kind), (12, "<1", "imported")
        )
        self.assertEqual(item.context["cell_line"], "HEK293")
        self.assertEqual(metrics[0].source_context_page, 11)

    def test_conflicting_native_metadata_cannot_reassign_one_namespace(self):
        for update in (
            {"source_table": "Table 3"},
            {"source_context_page": "10"},
            {"source_conditions_json": '{"cell_line":"A549","duration":"24 h"}'},
        ):
            with self.subTest(update=update):
                with self.assertRaises(WebError) as caught:
                    mapped_inputs(native_csv(second=update), self.mapping())
                self.assertEqual(caught.exception.code, "sar_csv_context_conflict")

    def test_condition_metadata_is_bounded_coherent_and_not_silently_dropped(self):
        fields = {"source_scope": "a" * 64, "source_context_page": "1"}
        for raw in (
            "{",
            "[]",
            '{"unknown":"X"}',
            '{"cell_line":false}',
            '{"cell_line":"HEK293","cell_line":"A549"}',
            '{"cell_line":"a\\u0000b"}',
            json.dumps({"duration": "x" * 1001}),
            json.dumps({"duration": "x" * 10001}),
        ):
            with self.subTest(raw=raw[:30]), self.assertRaises(WebError):
                native_scope_fields({**fields, "source_conditions_json": raw})
        with self.assertRaises(WebError):
            native_scope_fields({"source_conditions_json": '{"cell_line":"HEK293"}'})
        self.assertEqual(native_scope_fields({}), {})
        self.assertEqual(native_scope_fields({"source_conditions_json": "{}"}), {})

    def test_known_mapped_conditions_cannot_override_original_values_or_aliases(self):
        fields = {
            "source_conditions": {"cell_line": "HEK293", "treatment_duration": "24 h"}
        }
        for mapped in ({"cell_line": "A549"}, {"duration": "48 h"}):
            with self.subTest(mapped=mapped):
                with self.assertRaises(WebError) as caught:
                    native_conditions(mapped, fields)
                self.assertEqual(caught.exception.code, "sar_csv_context_conflict")
        self.assertEqual(
            native_conditions({"duration": None}, fields),
            {"duration": "24 h", "cell_line": "HEK293"},
        )
