"""Original unruled table scope, legends, continuations and conserved raw rows."""

import copy
import tempfile
import unittest
from pathlib import Path

import fitz
from patent_sar_extractor.artifact_io import load_json
from patent_sar_extractor.core.activity_extractor import extract
from patent_sar_extractor.core.activity_join import activity_evidence_errors
from patent_sar_extractor.core.activity_table_scopes import table_scope_groups
from patent_sar_extractor.core.activity_text import extract_text_tables
from patent_sar_extractor.core.activity_text_legend import read_legend
from patent_sar_extractor.core.activity_text_plan import (
    source_plan,
    validate_text_pages,
)

ROOT = "Table 73. Target: JAK; Assay: binding\nNo. | IC50 (nM)\n31 | 9"
METHOD = "Example 84: Binding assay\nCells were seeded. Reagent was added.\nResults are shown in Table 73."


class OriginalTextPayload(dict):
    """Keep the actual generated original alive beyond the temporary directory."""

    def __init__(self, payload, original_bytes):
        super().__init__(payload)
        self.original_bytes = original_bytes

    def open_original(self):
        return fitz.open(stream=self.original_bytes, filetype="pdf")


def facade(folder, *pages):
    path = folder / "original.pdf"
    with fitz.open() as doc:
        for text in pages:
            doc.new_page().insert_text((40, 60), text, fontsize=9)
        doc.save(path)
    extract(str(path), {"activity_pages": [0]}, str(folder / "output"))
    return OriginalTextPayload(
        load_json(folder / "output/activity_data.json", None), path.read_bytes()
    )


class TextOwnershipTests(unittest.TestCase):
    def test_multiple_split_metric_headers_keep_every_endpoint_before_row_parsing(self):
        result = extract_text_tables(
            [0],
            {
                "0": "Table A. Binding activity\nCompound ID\nIC50 (nM)\nDC50 (pM)\nA17 0.8 2.4"
            },
        )
        self.assertEqual([r.cpd for r in result.rows], ["Compound A17"])
        self.assertEqual(
            result.rows[0].activity_values, {"IC50 (nM)": "0.8", "DC50 (pM)": "2.4"}
        )

    def test_multiple_split_metric_headers_survive_actual_native_facade_and_replay(
        self,
    ):
        with tempfile.TemporaryDirectory() as temp:
            data = facade(
                Path(temp),
                "Table A. Binding activity\nCompound ID\nIC50 (nM)\nEC50 (nM)\nB80 0.7 3.1",
            )
        self.assertEqual([r["cpd"] for r in data["rows"]], ["Compound B80"])
        self.assertEqual(
            data["rows"][0]["activity_values"], {"IC50 (nM)": "0.7", "EC50 (nM)": "3.1"}
        )
        self.assertTrue(activity_evidence_errors(data, [0]))
        self.assertEqual(
            activity_evidence_errors(data, [0], open_original=data.open_original), []
        )

    def test_new_experiment_stops_same_page_rows_and_next_page_context_borrow(self):
        texts = {
            "0": ROOT
            + "\nExample 95: New proliferation assay\nOther cells were plated.\n44 | 0.3",
            "1": "45 | 0.4",
        }
        data = extract_text_tables([0, 1], texts)
        self.assertEqual([r.cpd for r in data.rows], ["Compound 31"])
        self.assertTrue(any(r["status"] == "unresolved" for r in data.coverage))

    def test_rows_repeated_header_and_literal_continued_caption_keep_one_scope(self):
        for continuation in (
            "44 | 0.3",
            "No. | IC50 (nM)\n44 | 0.3",
            "Table 73 (continued)\n44 | 0.3",
        ):
            with (
                self.subTest(continuation=continuation),
                tempfile.TemporaryDirectory() as temp,
            ):
                data = facade(Path(temp), METHOD, ROOT, continuation)
                self.assertEqual(
                    [r["cpd"] for r in data["rows"]], ["Compound 31", "Compound 44"]
                )
                self.assertEqual(
                    activity_evidence_errors(
                        data, [0], open_original=data.open_original
                    ),
                    [],
                )
                self.assertEqual(
                    data["coverage"]["references"][0]["status"], "resolved"
                )
                self.assertEqual(
                    len(data["coverage"]["references"][0]["target_region_ids"]), 2
                )
                self.assertEqual(
                    data["rows"][1]["activity_sources"][0]["target"], "JAK"
                )

    def test_changed_header_or_prose_does_not_borrow_old_context(self):
        for text in (
            "No. | IC50 (uM)\n44 | 0.3",
            "A different experiment was used.\n44 | 0.3",
            "Table 62. Other assay\n44 | 0.3",
        ):
            with self.subTest(text=text):
                data = extract_text_tables([0, 1], {"0": ROOT, "1": text})
                foreign = [r for r in data.rows if r.page_no == 2]
                self.assertTrue(
                    not foreign or all(r.table_id != "Table 73" for r in foreign)
                )

    def test_legend_from_later_table_cannot_rewrite_prior_raw_grade(self):
        text = "Table 73. Binding assay\nNo. | IC50 (nM)\n31 | A\nTable 62. Other assay\nletter codes for DC50 include: A (<1 nM) B (1-10 nM)\nNo. | DC50 (nM)\n44 | B"
        data = extract_text_tables([0], {"0": text})
        self.assertEqual(data.rows[0].activity_values, {"IC50 (nM)": "A"})
        self.assertNotIn("legend", data.rows[0].activity_sources[0])
        self.assertEqual(data.rows[1].activity_values, {"DC50 (nM)": "B"})

    def test_matching_original_legend_is_retained_without_numeric_substitution(self):
        text = "Table 73. Binding assay\nletter codes for IC50 include: A (<1 nM) B (1-10 nM)\nNo. | IC50 (nM)\n31 | A"
        data = extract_text_tables([0], {"0": text})
        self.assertEqual(data.rows[0].activity_values, {"IC50 (nM)": "A"})
        self.assertEqual(
            data.rows[0].activity_sources[0]["legend"], {"A": "<1 nM", "B": "1-10 nM"}
        )

    def test_serialized_text_population_context_and_original_row_are_rechecked(self):
        with tempfile.TemporaryDirectory() as temp:
            original = facade(Path(temp), METHOD, ROOT + "\n44 | 0.3")
        for mode in ("row_removed", "context_changed", "value_changed"):
            data = copy.deepcopy(original)
            if mode == "row_removed":
                data["rows"].pop()
            elif mode == "context_changed":
                data["rows"][0]["activity_sources"][0]["target"] = "BET"
            else:
                cell = data["rows"][0]["activity_sources"][0]["cells"][1]
                cell["observations"][0]["raw_text"] = "31 | 99"
            with self.subTest(mode=mode):
                try:
                    errors = activity_evidence_errors(
                        data, [0], open_original=data.open_original
                    )
                except (ValueError, TypeError):
                    continue
                self.assertTrue(errors)

    def test_original_observation_catalog_and_saved_continuation_flags_are_not_optional(
        self,
    ):
        with tempfile.TemporaryDirectory() as temp:
            original = facade(Path(temp), METHOD, ROOT, "44 | 0.3")
        for mode in (
            "catalog_removed",
            "span_changed",
            "parent_changed",
            "bad_source_page",
        ):
            data = copy.deepcopy(original)
            if mode == "catalog_removed":
                data["coverage"]["text_pages"] = {}
            elif mode == "span_changed":
                data["rows"][-1]["activity_sources"][0]["text_scope"]["span"] = [
                    0,
                    99999,
                ]
            elif mode == "parent_changed":
                data["rows"][-1]["activity_sources"][0]["text_scope"]["parent"] = [
                    1,
                    0,
                    3,
                ]
            else:
                data["rows"][-1]["activity_sources"][0]["page_no"] = None
            with self.subTest(mode=mode):
                try:
                    errors = activity_evidence_errors(
                        data, [0], open_original=data.open_original
                    )
                except (ValueError, TypeError):
                    continue
                self.assertTrue(errors)

    def test_header_only_start_requires_connected_actual_results(self):
        for continuation in ("44 | 0.3", "No. | IC50 (nM)\n44 | 0.3"):
            with (
                self.subTest(continuation=continuation),
                tempfile.TemporaryDirectory() as temp,
            ):
                data = facade(Path(temp), METHOD, ROOT.rsplit("\n", 1)[0], continuation)
                self.assertEqual([r["cpd"] for r in data["rows"]], ["Compound 44"])
                self.assertEqual(
                    activity_evidence_errors(
                        data, [0], open_original=data.open_original
                    ),
                    [],
                )
                self.assertEqual(
                    data["coverage"]["references"][0]["status"], "resolved"
                )
        with tempfile.TemporaryDirectory() as temp:
            data = facade(Path(temp), METHOD, ROOT.rsplit("\n", 1)[0])
        self.assertTrue(
            activity_evidence_errors(data, [0], open_original=data.open_original)
        )

    def test_repeated_measurements_and_disjoint_fields_keep_original_population(self):
        with tempfile.TemporaryDirectory() as temp:
            data = facade(
                Path(temp),
                ROOT + "\n31 | 9\n31 | 4",
                "Table 62. Other assay\nNo. | DC50 (nM)\n31 | 0.3",
            )
        self.assertEqual(len(data["rows"]), 3)
        self.assertEqual(
            [r["activity_values"]["IC50 (nM)"] for r in data["rows"]], ["9", "9", "4"]
        )
        self.assertEqual(
            activity_evidence_errors(data, [0], open_original=data.open_original), []
        )

    def test_pre_table_legend_keeps_original_span_and_only_proved_continuations(self):
        result = extract_text_tables(
            [0, 1],
            {
                "0": "letter codes for IC50 include: A (<1 nM) B (1-10 nM)\n"
                "Table 73. Binding assay\nNo. | IC50 (nM)\n31 | A",
                "1": "Table 73. Continued\nNo. | IC50 (nM)\n44 | B\n"
                "Table 74. Another binding assay\nNo. | IC50 (nM)\n45 | B",
            },
        )
        self.assertEqual(
            [row.cpd for row in result.rows],
            ["Compound 31", "Compound 44", "Compound 45"],
        )
        for row in result.rows[:2]:
            self.assertEqual(
                row.activity_sources[0]["legend"], {"A": "<1 nM", "B": "1-10 nM"}
            )
        self.assertEqual(result.rows[0].activity_sources[0]["text_scope"]["span"][0], 0)
        self.assertNotIn("legend", result.rows[2].activity_sources[0])

    def test_pre_table_legend_with_a_different_endpoint_is_retained_as_review(self):
        result = extract_text_tables(
            [0],
            {
                "0": "letter codes for IC50 include: A (<1 nM) B (1-10 nM)\n"
                "Table 73. Degradation assay\nNo. | DC50 (nM)\n31 | A",
            },
        )
        self.assertEqual(result.rows[0].activity_values, {"DC50 (nM)": "A"})
        self.assertTrue(result.rows[0].needs_review)
        self.assertTrue(result.rows[0].activity_sources[0]["legend_issues"])

    def test_conflicting_or_unit_mismatched_legend_preserves_raw_grade_and_refuses_acceptance(
        self,
    ):
        for legend in (
            "letter codes for IC50 include: A (<1 nM) B (1-10 nM) A (>100 nM)",
            "letter codes for IC50 include: A (<1 uM) B (1-10 uM)",
            "letter codes for IC50 include: A (<1 nM) B (1-10 nM)\nletter codes for IC50 include: A (>100 nM) B (10-100 nM)",
            "letter codes for IC50 are defined by A (<1 nM) B (1-10 nM)",
        ):
            with self.subTest(legend=legend):
                result = extract_text_tables(
                    [0],
                    {
                        "0": "Table 73. Binding assay\n"
                        + legend
                        + "\nNo. | IC50 (nM)\n31 | A"
                    },
                )
                self.assertEqual(result.rows[0].activity_values, {"IC50 (nM)": "A"})
                self.assertTrue(result.rows[0].needs_review)

    def test_page_marker_cannot_reassign_physical_original_owner(self):
        result = extract_text_tables(
            [0], {"0": "[[PAGE 99]]\n" + ROOT.replace("31 |", "[[PAGE 99]]\n31 |")}
        )
        self.assertEqual(result.rows[0].page_no, 1)
        self.assertEqual(result.rows[0].activity_sources[0]["page_no"], 1)

    def test_saved_review_flag_cannot_hide_an_original_legend_contradiction(self):
        with tempfile.TemporaryDirectory() as temp:
            data = facade(
                Path(temp),
                "Table 73. Binding assay\nletter codes for IC50 include: A (<1 uM) B (1-10 uM)\nNo. | IC50 (nM)\n31 | A",
            )
        self.assertTrue(data["rows"][0]["needs_review"])
        data["rows"][0]["needs_review"] = False
        self.assertTrue(
            activity_evidence_errors(data, [0], open_original=data.open_original)
        )

    def test_multiline_header_only_continuation_and_original_inventory_bounds(self):
        result = extract_text_tables(
            [0, 1], {"0": "Table 73. Binding assay\nNo.\nIC50 (nM)", "1": "44 | 0.3"}
        )
        self.assertEqual([r.cpd for r in result.rows], ["Compound 44"])
        for pages in ({"01": ROOT}, {"1": None}, {"1": "x" * 100001}, {"10001": ROOT}):
            with self.subTest(pages_shape=list(pages)), self.assertRaises(ValueError):
                validate_text_pages(pages)
        with self.assertRaises(ValueError):
            source_plan({"2": ROOT}, page_count=1)
        with self.assertRaises(ValueError):
            read_legend("letter codes for IC50 include: A (<1 nM) B (1-10 nM) " * 33)

    def test_over_bound_connected_table_is_refused_without_silent_truncation(self):
        texts = {
            "0": ROOT,
            **{str(index): f"{index + 100} | 0.3" for index in range(1, 129)},
        }
        data = extract_text_tables(list(range(129)), texts)
        self.assertEqual(len(data.rows), 129)
        self.assertEqual(len(data.coverage), 129)
        with self.assertRaises(ValueError):
            table_scope_groups(data.coverage)

    def test_missing_original_page_terminates_text_context(self):
        result = extract_text_tables([0, 2], {"0": ROOT, "2": "44 | 0.3"})
        self.assertEqual([r.cpd for r in result.rows], ["Compound 31"])

    def test_running_headers_can_continue_but_unknown_preface_and_suffix_cannot(self):
        for tail, next_page, expected in (
            ("\nPCT/US2026/12345", "WO2026/98765\n44 | 0.3", 2),
            ("\nA different procedure was performed.", "44 | 0.3", 1),
            ("", "Cells were incubated for a different time.\n44 | 0.3", 1),
        ):
            with self.subTest(tail=tail, next_page=next_page):
                result = extract_text_tables([0, 1], {"0": ROOT + tail, "1": next_page})
                self.assertEqual(len(result.rows), expected)

    def test_unassigned_prefixed_identifiers_remain_in_explicit_source_coverage(self):
        result = extract_text_tables(
            [0, 1],
            {
                "0": ROOT + "\nExample 62: New cell proliferation assay",
                "1": "Compound I-44A | 0.3",
            },
        )
        self.assertEqual([r.cpd for r in result.rows], ["Compound 31"])
        self.assertTrue(
            any(
                r["page_no"] == 2 and r["status"] == "unresolved"
                for r in result.coverage
            )
        )
