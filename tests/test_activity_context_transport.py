"""Real generated native/text table producers conserve original declarations."""

import copy
import hashlib
import tempfile
import unittest
from pathlib import Path

import fitz

from patent_sar_extractor.artifact_io import load_json
from patent_sar_extractor.core.activity_coordinates import extract_coordinate_tables
from patent_sar_extractor.core.activity_coverage import (
    coverage_errors,
    coverage_packet,
    source_record,
)
from patent_sar_extractor.core.activity_extractor import extract
from patent_sar_extractor.core.activity_text import extract_text_tables
from patent_sar_extractor.web.artifacts import _activities
from patent_sar_extractor.web.sar.observation_contexts import ObservationContexts
from tests.test_activity_context_windows import draw_grid

FIELDS = {
    "target": "Human kinase domain",
    "assay": "HTRF binding",
    "cell_line": "HEK293",
    "construct": "WT 1-300",
    "duration": "24 h",
    "timepoint": "48 h",
    "batch": "B1",
}
PREFIX = (
    "Table 7. Comparison of compound measurements\nTarget: Human kinase domain\n"
    "Assay: HTRF binding\nCell line: HEK293\nConstruct: WT 1-300\nDuration: 24 h\n"
    "Timepoint: 48 h\nBatch: B1"
)


class ActivityContextTransportTests(unittest.TestCase):
    def parse_grid(self, *, transposed=False):
        with fitz.open() as document:
            page = document.new_page(width=500, height=600)
            page.insert_text((40, 45), PREFIX, fontsize=9)
            if transposed:
                draw_grid(
                    page,
                    300,
                    [["", "Compound 1", "Compound 2"], ["IC50 (nM)", "1", "2"]],
                    xs=[40, 170, 310, 450],
                )
            else:
                draw_grid(page, 300, [["No.", "IC50 (nM)"], ["1", "1"], ["2", "2"]])
            return extract_coordinate_tables(document, [0])

    def check_fields(self, parsed):
        self.assertEqual(len(parsed.rows), 2)
        for row in parsed.rows:
            source = row.activity_sources[0]
            self.assertEqual({key: source.get(key) for key in FIELDS}, FIELDS)
        pages = sorted(parsed.owned_pages)
        packet = coverage_packet(
            pages, parsed.coverage, parsed.rows, text_pages=parsed.text_pages
        )
        self.assertEqual(coverage_errors(packet, pages, rows=parsed.rows), [])
        return packet

    def test_native_grid_keeps_every_declared_condition_and_refuses_a_forged_duration(
        self,
    ):
        parsed = self.parse_grid()
        packet = self.check_fields(parsed)
        forged = copy.deepcopy(parsed.rows)
        forged[0].activity_sources[0]["duration"] = "48 h"
        self.assertTrue(coverage_errors(packet, [0], rows=forged))

    def test_native_transposed_grid_keeps_conditions_and_refuses_a_forged_duration(
        self,
    ):
        parsed = self.parse_grid(transposed=True)
        packet = self.check_fields(parsed)
        forged = copy.deepcopy(parsed.rows)
        forged[0].activity_sources[0]["duration"] = "48 h"
        self.assertTrue(coverage_errors(packet, [0], rows=forged))

    def test_delimited_text_and_its_adjacent_continuation_keep_the_original_context(
        self,
    ):
        text = PREFIX + "\nCompound No. | IC50 (nM)\n1 | 1"
        parsed = extract_text_tables(
            [0, 1], {"0": text, "1": "Table 7 (continued)\n2 | 2"}
        )
        packet = self.check_fields(parsed)
        self.assertEqual(
            parsed.rows[1].activity_sources[0]["text_scope"]["origin"][0], 1
        )
        forged = copy.deepcopy(parsed.rows)
        forged[1].activity_sources[0]["batch"] = "B2"
        self.assertTrue(coverage_errors(packet, [0, 1], rows=forged))

    def test_serialized_transposed_context_cannot_be_changed_alongside_its_rows(self):
        parsed = self.parse_grid(transposed=True)
        packet = self.check_fields(parsed)
        forged = copy.deepcopy(packet)
        root = next(r for r in forged["regions"] if "transposed_layout" in r)
        root["transposed_layout"]["context"]["duration"] = "48 h"
        # Rehash the modified carrier: a self-consistent saved digest is not
        # sufficient proof of the captured original declaration.
        replacement = source_record(
            root["page_no"],
            root["kind"],
            root["bbox"],
            root["table_id"],
            root["header"],
            root["status"],
            root["reason"],
            root["row_count"],
            grid_axes=root["grid_axes"],
            transposed_layout=root["transposed_layout"],
        )
        root.clear()
        root.update(replacement)
        rows = copy.deepcopy(parsed.rows)
        for row in rows:
            row.activity_sources[0]["duration"] = "48 h"
        self.assertTrue(coverage_errors(forged, [0], rows=rows))

    def test_formal_native_writer_and_sar_reader_keep_conditions_without_alternative_calculation(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "controlled.pdf"
            with fitz.open() as document:
                page = document.new_page(width=500, height=600)
                page.insert_text((40, 45), PREFIX, fontsize=9)
                draw_grid(page, 300, [["No.", "IC50 (nM)"], ["1", "1"], ["2", "2"]])
                document.save(source)
            extract(str(source), {"activity_pages": [0]}, str(root / "activity"))
            payload = load_json(root / "activity/activity_data.json", None)
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            contexts = ObservationContexts(
                {
                    "run_root": str(root),
                    "sha256": digest,
                    "expected_sha256": digest,
                    "page_count": 1,
                }
            )
            activities = [
                _activities(row, page_count=1, document_sha256=digest)[0]
                for row in payload["rows"]
            ]
            self.assertEqual(len(activities), 2)
            for row, activity in zip(payload["rows"], activities, strict=True):
                self.assertEqual(contexts.contexts(row["cpd"], activity), [FIELDS])
                self.assertEqual(activity.source_conditions["construct"], "WT 1-300")
                self.assertNotIn("treatment_duration", activity.source_conditions)
