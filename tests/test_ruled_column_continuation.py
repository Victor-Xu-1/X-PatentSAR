"""Real original physical continuations, not fabricated headers or ID order."""

import copy
import json
import unittest

from test_unruled_continuation import continued_page
from unruled_structure_support import UnruledStructureControls

from patent_sar_extractor.core.binding_source_references import (
    reference_issues,
    reference_scope,
)
from patent_sar_extractor.core.formal_structure import coverage_errors
from patent_sar_extractor.core.source_evidence_identity import proof_id
from patent_sar_extractor.web.compound_catalog import read_compound_catalog


def physical_parts(
    first,
    structures,
    *,
    gap=False,
    prefix="",
    offset=0,
    missing_first=False,
    initial_ruled=True,
    frame_xs=(40, 175, 380),
):
    document = first.parent
    if initial_ruled:
        for x in (40, 175, 380):
            first.draw_line((x, 65), (x, 330))
        for y in (65, 100, 210, 330):
            first.draw_line((40, y), (380, y))
    continued_page(first, structures, gap=gap, caption=prefix, offset=offset)
    page = document[-1]
    for x in frame_xs:
        page.draw_line((x, 80 + offset), (x, 320 + offset))
    for y in (80, 200, 320):
        page.draw_line((frame_xs[0], y + offset), (frame_xs[-1], y + offset))
    if missing_first:
        structures[:] = [
            s for s in structures if s["structure_id"] != f"C{page.number}-0"
        ]


class RuledColumnContinuationTests(UnruledStructureControls, unittest.TestCase):
    def test_original_unruled_parent_can_continue_as_actual_ruled_rows(self):
        result, payload = self.run_binding(
            ["73", "28"],
            mutate_page=lambda p, s: physical_parts(p, s, initial_ruled=False),
        )
        self.assertEqual(
            {r["cpd"] for r in result["bindings"]},
            {
                "Compound 73",
                "Compound 28",
                "Compound 901A",
                "Compound I-003B",
            },
        )
        self.assertEqual(coverage_errors(payload), [])

    def test_known_activity_header_does_not_inherit_previous_structure_columns(self):
        self.measurement_title = "Table 13. Binding assay"
        self.measurement_header = "IC50 (nM)"

        def activity_after_structure(first, _structures):
            for x in (40, 175, 380):
                first.draw_line((x, 65), (x, 330))
            for y in (65, 100, 210, 330):
                first.draw_line((40, y), (380, y))
            document = first.parent
            page = document.new_page(width=520, height=720)
            if self.measurement_title:
                page.insert_text((40, 45), self.measurement_title, fontsize=10)
            for x in (40, 175, 380):
                page.draw_line((x, 65), (x, 220))
            for y in (65, 100, 160, 220):
                page.draw_line((40, y), (380, y))
            for top, values in (
                (80, ("Compound No.", self.measurement_header)),
                (135, ("901A", "0.3")),
                (195, ("I-003B", "0.8")),
            ):
                page.insert_text((50, top), values[0], fontsize=10)
                page.insert_text((230, top), values[1], fontsize=10)

        for title in ("Table 13. Binding assay", ""):
            with self.subTest(title=title):
                self.measurement_title = title
                result, payload = self.run_binding(
                    ["73", "28"], mutate_page=activity_after_structure
                )
                self.assertEqual(
                    {r["cpd"] for r in result["bindings"]},
                    {"Compound 73", "Compound 28"},
                )
                self.assertEqual(coverage_errors(payload), [])
        # Without a positive known measurement role, retain the unresolved frame.
        self.measurement_header = "Unspecified result"
        result, payload = self.run_binding(
            ["73", "28"], mutate_page=activity_after_structure
        )
        self.assertEqual(len(result["bindings"]), 2)
        self.assertTrue(coverage_errors(payload))

    def test_logical_to_physical_columns_keep_original_header_word_ownership(self):
        for edges, accepted in (((45, 180, 400), True), ((40, 90, 380), False)):
            with self.subTest(edges=edges):
                result, payload = self.run_binding(
                    ["73", "28"],
                    mutate_page=lambda p, s, edges=edges: physical_parts(
                        p, s, initial_ruled=False, frame_xs=edges
                    ),
                )
                self.assertEqual(
                    len(result["bindings"]),
                    4 if accepted else 2,
                    payload["source_issues"],
                )
                self.assertEqual(not coverage_errors(payload), accepted)

    def test_scanned_unruled_parent_uses_the_same_actual_ruled_cell_proof(self):
        result, payload = self.run_binding(
            ["73", "28"],
            raster=True,
            mutate_page=lambda p, s: physical_parts(p, s, initial_ruled=False),
        )
        self.assertEqual(len(result["bindings"]), 4)
        self.assertEqual(coverage_errors(payload), [])

    def test_measurement_shaped_header_cannot_hide_an_observed_chemical_frame(self):
        def mixed_frame(first, structures):
            document = first.parent
            physical_parts(first, structures)
            page = document[-1]
            page.insert_text((50, 100), "Compound No.", fontsize=10)
            page.insert_text((230, 100), "IC50 (nM)", fontsize=10)

        _, payload = self.run_binding(["73", "28"], mutate_page=mixed_frame)
        roots = [
            s
            for s in payload["source_sections"]
            if s["role"] == "structure_column_anchor" and s["page_no"] == 2
        ]
        self.assertEqual(len(roots), 1)
        self.assertEqual(len(roots[0]["source"]["page_diagrams"]), 2)
        self.assertTrue(coverage_errors(payload))

    def test_headerless_first_row_survives_at_different_original_page_positions(self):
        for offset in (0, 150):
            with self.subTest(offset=offset):
                result, payload = self.run_binding(
                    ["73", "28"],
                    mutate_page=lambda p, s, offset=offset: physical_parts(
                        p, s, offset=offset
                    ),
                )
                self.assertEqual(len(result["bindings"]), 4)
                self.assertEqual(coverage_errors(payload), [])
                roots = [
                    s
                    for s in payload["source_sections"]
                    if s["role"] == "structure_column_anchor"
                ]
                child = roots[-1]["source"]
                self.assertEqual(
                    child["header_scope"]["kind"], "continued_ruled_columns"
                )
                self.assertEqual(
                    child["body_context"][0]["bbox"][1], child["grid_axes"]["ys"][0]
                )
                saved = json.loads(json.dumps(payload))
                self.assertEqual(
                    len(read_compound_catalog(saved, saved["final_bindings"])[0]), 4
                )

    def test_gap_and_unrelated_original_prefix_cannot_borrow_column_roles(self):
        for options in (
            {"gap": True},
            {"prefix": "Compound B80: Preparation"},
            {"prefix": "A different experiment was performed."},
        ):
            with self.subTest(options=options):
                result, payload = self.run_binding(
                    ["73", "28"],
                    mutate_page=lambda p, s, options=options: physical_parts(
                        p, s, **options
                    ),
                )
                self.assertEqual(len(result["bindings"]), 2)
                self.assertTrue(coverage_errors(payload))

    def test_missing_first_diagram_is_a_gap_not_a_shifted_second_row(self):
        result, payload = self.run_binding(
            ["73", "28"],
            mutate_page=lambda p, s: physical_parts(p, s, missing_first=True),
        )
        self.assertEqual(len(result["bindings"]), 3)
        self.assertNotIn("Compound 901A", [r["cpd"] for r in result["bindings"]])
        self.assertTrue(coverage_errors(payload))

    def test_no_detector_hits_do_not_erase_the_next_original_closed_rows(self):
        def missed_page(first, structures):
            physical_parts(first, structures)
            structures[:] = [s for s in structures if s["page_no"] == 1]

        result, payload = self.run_binding(["73", "28"], mutate_page=missed_page)
        self.assertEqual(len(result["bindings"]), 2)
        self.assertTrue(coverage_errors(payload))
        children = [
            s
            for s in payload["source_sections"]
            if s["role"] == "structure_column_anchor" and s["page_no"] == 2
        ]
        self.assertEqual(len(children), 1)
        self.assertTrue(children[0]["source"]["header_scope"]["parent_region_id"])

    def test_rehashed_foreign_parent_cannot_approve_a_saved_continuation(self):
        _, payload = self.run_binding(["73", "28"], mutate_page=physical_parts)
        payload = copy.deepcopy(payload)
        child = [
            s
            for s in payload["source_sections"]
            if s["role"] == "structure_column_anchor"
        ][-1]
        old = child["region_id"]
        child["source"]["header_scope"]["parent_region_id"] = "e" * 64
        child["region_id"] = proof_id(child["source"])
        for row in [
            *payload["compound_catalog"]["entries"],
            *payload["final_bindings"],
        ]:
            ownership = (row.get("numbered_table_cell_evidence") or {}).get(
                "column_ownership", {}
            )
            if ownership.get("source_anchor_id") == old:
                ownership.update(
                    source_anchor_id=child["region_id"],
                    header_scope=child["source"]["header_scope"],
                )
        payload["source_reference_scope"] = reference_scope(
            payload["source_sections"],
            payload["source_reference_scope"]["original_pdf_sha256"],
        )
        payload["source_issues"] = []
        with self.assertRaises(ValueError):
            reference_issues(payload, payload["compound_catalog"]["entries"])
