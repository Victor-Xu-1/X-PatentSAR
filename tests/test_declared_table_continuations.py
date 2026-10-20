"""Literal repeated conditions on continued tables are conserved, not inferred."""

import copy
import hashlib
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import fitz

from patent_sar_extractor.artifact_io import load_json
from patent_sar_extractor.core.activity_auxiliary_replay import original_pdf_reader
from patent_sar_extractor.core.activity_continuation_policy import continuation_allowed
from patent_sar_extractor.core.activity_coordinates import extract_coordinate_tables
from patent_sar_extractor.core.activity_coverage import coverage_errors, coverage_packet
from patent_sar_extractor.core.activity_extractor import extract
from patent_sar_extractor.core.activity_headers import context_from_text
from patent_sar_extractor.core.activity_join import activity_evidence_errors
from patent_sar_extractor.core.activity_text import extract_text_tables
from patent_sar_extractor.web.artifacts import _activities
from tests.test_activity_context_windows import draw_grid

DECLARATIONS = {
    "Target": "Human kinase domain",
    "Assay": "HTRF binding",
    "Cell line": "HEK293",
    "Construct": "WT 1-300",
    "Duration": "24 h",
    "Treatment duration": "24 h",
    "Timepoint": "48 h",
    "Batch": "B1",
}
ORIGINAL = "Table 71. Binding activity\n" + "\n".join(
    f"{key}: {value}" for key, value in DECLARATIONS.items()
)
CONTINUED = "Table 71 (continued)\nAssay: HTRF binding\nDuration: 24 h"


def draw_document(document, *, continued=CONTINUED):
    page = document.new_page(width=500, height=600)
    page.insert_text((40, 40), ORIGINAL, fontsize=8)
    draw_grid(page, 300, [["No.", "IC50 (nM)"], ["7", "3"]])
    page = document.new_page(width=500, height=600)
    page.insert_text((40, 40), continued, fontsize=8)
    draw_grid(page, 100, [["19", "4"]])


class DeclaredTableContinuationTests(unittest.TestCase):
    def test_each_literal_repeated_condition_is_a_continuation_not_a_new_assay(self):
        context = context_from_text(ORIGINAL)
        for label, value in DECLARATIONS.items():
            with self.subTest(label=label):
                self.assertTrue(
                    continuation_allowed(
                        f"Table 71 (continued)\n{label}: {value}", None, context
                    )
                )
        self.assertTrue(
            continuation_allowed(
                "Table 71 (continued); Assay: HTRF binding; Duration: 24 h",
                None,
                context,
            )
        )

    def test_changed_conditions_unknown_fields_and_free_prose_cannot_borrow(self):
        context = context_from_text(ORIGINAL)
        for label in DECLARATIONS:
            with self.subTest(label=label):
                self.assertFalse(
                    continuation_allowed(
                        f"Table 71 (continued)\n{label}: Different", None, context
                    )
                )
        for prefix in (
            "Table 71 (continued)\nAssay: HTRF binding\nA different experiment follows.",
            "Example 92. New experiment\n" + CONTINUED,
            "Table 71 (continued)\nTemperature: 37 C",
            "Table 72 (continued)\nDuration: 24 h",
            "Table 71 (continued)\nDuration:",
            CONTINUED + "\nDuration: 48 h",
            "Duration: 24 h",
        ):
            with self.subTest(prefix=prefix):
                self.assertFalse(continuation_allowed(prefix, None, context))
        self.assertFalse(
            continuation_allowed(
                CONTINUED, None, context_from_text("Table 71. Binding activity")
            )
        )
        self.assertFalse(
            continuation_allowed(CONTINUED, {"suffix": "New assay section"}, context)
        )

    def test_generated_native_continuation_keeps_rows_conditions_and_source_family(
        self,
    ):
        with fitz.open() as document:
            draw_document(document)
            parsed = extract_coordinate_tables(document, [0])
        self.assertEqual(
            [row.cpd for row in parsed.rows], ["Compound 7", "Compound 19"]
        )
        packet = coverage_packet(
            [0],
            parsed.coverage,
            parsed.rows,
            text_pages=parsed.text_pages,
        )
        self.assertEqual(coverage_errors(packet, [0], rows=parsed.rows), [])
        source = parsed.rows[-1].activity_sources[0]
        self.assertEqual(source["assay"], "HTRF binding")
        self.assertEqual(source["duration"], "24 h")
        self.assertEqual(source["header_region"]["page_no"], 1)
        altered = copy.deepcopy(packet)
        continuation = next(
            item
            for item in altered["regions"]
            if item.get("layout") and item["page_no"] == 2
        )
        continuation["layout"]["boundary_prefix"] = CONTINUED.replace("24 h", "48 h")
        with self.assertRaisesRegex(ValueError, "boundary differs"):
            coverage_errors(altered, [0], rows=parsed.rows)

    def test_delimited_text_continuation_uses_the_same_known_condition_rule(self):
        parsed = extract_text_tables(
            [0, 1],
            {
                "0": ORIGINAL + "\nCompound No. | IC50 (nM)\n7 | 3",
                "1": CONTINUED + "\n19 | 4",
            },
        )
        self.assertEqual(
            [row.cpd for row in parsed.rows], ["Compound 7", "Compound 19"]
        )
        packet = coverage_packet(
            sorted(parsed.owned_pages),
            parsed.coverage,
            parsed.rows,
            text_pages=parsed.text_pages,
        )
        self.assertEqual(coverage_errors(packet, [0, 1], rows=parsed.rows), [])
        self.assertEqual(parsed.rows[-1].activity_sources[0]["duration"], "24 h")
        changed = copy.deepcopy(packet)
        changed["text_pages"]["1"] = changed["text_pages"]["1"].replace("24 h", "48 h")
        with self.assertRaisesRegex(ValueError, "Text inventory differs"):
            coverage_errors(changed, [0, 1], rows=parsed.rows)

    def test_formal_native_writer_keeps_one_sar_namespace_and_distinct_measurement_pages(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = root / "controlled.pdf"
            with fitz.open() as document:
                draw_document(document)
                document.save(original)
            extract(str(original), {"activity_pages": [0]}, str(root / "activity"))
            data = load_json(root / "activity/activity_data.json", None)
            self.assertTrue(activity_evidence_errors(data, [0]))
            self.assertEqual(
                activity_evidence_errors(
                    data, [0], open_original=original_pdf_reader(original)
                ),
                [],
            )
            self.assertEqual(
                [row["cpd"] for row in data["rows"]], ["Compound 7", "Compound 19"]
            )
            digest = hashlib.sha256(original.read_bytes()).hexdigest()
            observed = [
                _activities(row, page_count=2, document_sha256=digest)[0]
                for row in data["rows"]
            ]
            self.assertEqual(observed[0].source_scope, observed[1].source_scope)
            self.assertTrue(observed[0].source_scope)
            self.assertEqual([row.page for row in observed], [1, 2])
            self.assertTrue(all(row.source_context_page == 1 for row in observed))
            self.assertTrue(
                all(row.source_conditions["duration"] == "24 h" for row in observed)
            )

    def test_repeated_declarations_never_convert_units_or_fill_unknown_parent_fields(
        self,
    ):
        context = context_from_text("Table 71. Binding activity\nDuration: 1 day")
        self.assertFalse(continuation_allowed(CONTINUED, None, context))
        duration = context_from_text("Table 71. Binding activity\nDuration: 24 h")
        self.assertTrue(
            continuation_allowed(
                "Table 71 (continued)\nTreatment duration: 24 h", None, duration
            )
        )
        self.assertFalse(
            continuation_allowed("Table 71 (continued)\nBatch: B1", None, duration)
        )
        self.assertFalse(
            continuation_allowed(
                "Table 71 (continued)\nDuration: 24 h",
                None,
                replace(duration, treatment_duration="48 h"),
            )
        )

    def test_running_text_chinese_labels_and_one_literal_value_line_share_the_rule(
        self,
    ):
        context = context_from_text(ORIGINAL)
        for prefix in (
            "WO2028/008765\n" + CONTINUED,
            "Table 71 (continued)\nBatch:\nB1",
            "Table 71（续）\n实验：HTRF binding；处理时长：24 h",
            "Table 71 (continued)\nAssay name: HTRF binding",
        ):
            with self.subTest(prefix=prefix):
                self.assertTrue(continuation_allowed(prefix, None, context))
        self.assertFalse(continuation_allowed(" " * 10001, None, context))

    def test_unconsumed_or_excess_context_cannot_disappear_before_continuation(self):
        context = context_from_text(ORIGINAL)
        for suffix in (
            "Assay: HTRF binding; new method",
            "Assay: HTRF binding\n\nNew method",
            "Assay:\n\nHTRF binding",
            "Batch: " + "B" * 1001,
            "\n".join(["Batch: B1"] * 33),
            "Batch: B1" + " " * 10001,
        ):
            with self.subTest(suffix=suffix[:80]):
                self.assertFalse(
                    continuation_allowed(
                        "Table 71 (continued)\n" + suffix, None, context
                    )
                )
