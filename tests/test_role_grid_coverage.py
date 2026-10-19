"""Whole original grids cannot be silently sampled at a per-work-unit bound."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz

from patent_sar_extractor.core.activity_grid_role_observation import (
    observe_characterization,
)
from patent_sar_extractor.core.activity_grid_role_proof import valid_role_scope
from patent_sar_extractor.core.binding_source_regions import identifier_references
from patent_sar_extractor.core.source_geometry import SourceTokens, source_layout


class RoleGridCoverageTests(unittest.TestCase):
    def original(self, count, *, last_text=None):
        document = fitz.open()
        self.addCleanup(document.close)
        page = document.new_page(width=620, height=110 + 18 * (count + 1))
        xs = [30, 125, 340, 590]
        ys = [70 + 18 * row for row in range(count + 2)]
        matrix = [["Compound No.", "Preparation", "Characterization"]]
        identifiers = [f"{index:03d}B" for index in range(1, count + 1)]
        for identifier in identifiers:
            matrix.append(
                [
                    identifier,
                    "Prepared according to Compound 091C",
                    "1H NMR (400 MHz) 7.2 ppm; MS m/z 413.1",
                ]
            )
        if last_text is not None:
            matrix[-1][-1] = last_text
        for row, values in enumerate(matrix):
            for column, text in enumerate(values):
                page.insert_text((xs[column] + 3, ys[row] + 12), text, fontsize=7)
        for x in xs:
            page.draw_line((x, ys[0]), (x, ys[-1]))
        for y in ys:
            page.draw_line((xs[0], y), (xs[-1], y))
        layout = source_layout(page)
        return (
            page,
            {"xs": xs, "ys": ys},
            SourceTokens(layout.native, layout),
            identifiers,
        )

    def observe(self, count, *, last_text=None):
        page, grid, tokens, identifiers = self.original(count, last_text=last_text)
        failures = []
        with patch(
            "patent_sar_extractor.core.activity_grid_role_observation.get_ocr_engine",
            side_effect=AssertionError("This fully native source must not invoke OCR"),
        ):
            proof = observe_characterization(
                page,
                grid,
                tokens,
                "Table J. Compound characterization",
                evidence_sink=failures,
            )
        return proof, failures, grid, identifiers

    def assert_complete(self, count):
        proof, failures, grid, identifiers = self.observe(count)
        self.assertIsNotNone(proof, [failure["reason"] for failure in failures])
        self.assertEqual(failures, [])
        bounds = [grid["xs"][0], grid["ys"][0], grid["xs"][-1], grid["ys"][-1]]
        region = {
            "page_no": 1,
            "region_id": "controlled-complete-region",
            "bbox": bounds,
            "role_scope": proof,
        }
        self.assertTrue(valid_role_scope(region))
        self.assertEqual(proof["xs"], grid["xs"])
        self.assertEqual(proof["ys"], grid["ys"])
        references = identifier_references(region)
        self.assertEqual([record["identifier"] for record in references], identifiers)
        self.assertTrue(
            all(record["source_role"] == "terminal_reference" for record in references)
        )

    def test_native_original_control_at_the_existing_work_unit_boundary(self):
        self.assert_complete(31)  # Header +31 complete rows ==96 physical cells.

    def test_every_original_closed_row_survives_more_than_one_work_unit(self):
        for count in (32, 66):
            with self.subTest(rows=count):
                self.assert_complete(count)

    def test_unknown_last_cell_cannot_be_sampled_out_as_spectral(self):
        proof, failures, _grid, _identifiers = self.observe(
            66, last_text="Unclassified original observation"
        )
        self.assertIsNone(proof)
        self.assertEqual(
            [item["reason"] for item in failures], ["unresolved_column_roles"]
        )

    def test_measurement_in_the_last_row_cannot_be_excluded_as_characterization(self):
        proof, failures, _grid, _identifiers = self.observe(
            66, last_text="1H NMR (400 MHz); IC50 = 3 nM"
        )
        self.assertIsNone(proof)
        self.assertEqual(
            [item["reason"] for item in failures], ["native_measurement_conflict"]
        )

    def test_work_units_cover_every_physical_cell_once_without_expanding_unit_budget(
        self,
    ):
        from patent_sar_extractor.core import activity_grid_role_observation as observer

        with patch.object(
            observer, "_observe_role_cells", wraps=observer._observe_role_cells
        ) as units:
            proof, failures, grid, _identifiers = self.observe(66)
        self.assertEqual(failures, [])
        self.assertEqual(proof["work_windows"], [[0, 32], [32, 64], [64, 67]])
        self.assertEqual(len(units.call_args_list), 3)
        for call, (start, stop) in zip(units.call_args_list, proof["work_windows"]):
            unit = call.args[1]
            self.assertEqual(unit["xs"], grid["xs"])
            self.assertEqual(unit["ys"], grid["ys"][start : stop + 1])
            self.assertLessEqual((len(unit["xs"]) - 1) * (len(unit["ys"]) - 1), 96)

    def test_partial_duplicate_reordered_and_downgraded_grids_are_not_complete(self):
        proof, _failures, grid, _identifiers = self.observe(66)
        box = [grid["xs"][0], grid["ys"][0], grid["xs"][-1], grid["ys"][-1]]
        for mutation in (
            "missing_windows",
            "partial_windows",
            "duplicate_windows",
            "reversed_windows",
            "boolean_index",
            "missing_tail",
            "exchanged_ids",
            "downgraded",
        ):
            with self.subTest(mutation=mutation):
                changed = json.loads(json.dumps(proof))
                if mutation == "missing_windows":
                    del changed["work_windows"]
                elif mutation == "partial_windows":
                    changed["work_windows"].pop()
                elif mutation == "duplicate_windows":
                    changed["work_windows"][1] = changed["work_windows"][0]
                elif mutation == "reversed_windows":
                    changed["work_windows"].reverse()
                elif mutation == "boolean_index":
                    changed["work_windows"][0][0] = False
                elif mutation == "missing_tail":
                    changed["native_hints"].pop()
                elif mutation == "exchanged_ids":
                    observed = changed["observations"][0]
                    observed["matrix"][1][0], observed["matrix"][2][0] = (
                        observed["matrix"][2][0],
                        observed["matrix"][1][0],
                    )
                    observed["cells"][3]["text"] = observed["matrix"][1][0]
                    observed["cells"][6]["text"] = observed["matrix"][2][0]
                else:
                    changed["version"] = 1
                    del changed["work_windows"]
                self.assertFalse(valid_role_scope({"bbox": box, "role_scope": changed}))

    def test_untrusted_or_excessive_axes_refuse_without_rendering_or_truncation(self):
        from patent_sar_extractor.core.role_grid_windows import (
            role_grid_shape,
            role_work_windows,
        )

        for xs, ys in (
            ([0, 10], [0, 1, 1]),
            ([0, True, 10], [0, 10]),
            ([0, 10**400], [0, 10]),
            ([0, float("nan")], [0, 10]),
            ([0, float("inf")], [0, 10]),
            ([0, 10], list(range(4098))),
            (list(range(66)), [0, 10]),
        ):
            with self.subTest(xs_length=len(xs), ys_length=len(ys)):
                self.assertIsNone(role_grid_shape(xs, ys))
                self.assertIsNone(role_work_windows(xs, ys))

    def test_shared_artifact_round_trip_keeps_the_complete_original_reference_pool(
        self,
    ):
        from patent_sar_extractor.artifact_io import load_json, write_json_atomic

        proof, _failures, grid, identifiers = self.observe(66)
        record = {
            "bbox": [grid["xs"][0], grid["ys"][0], grid["xs"][-1], grid["ys"][-1]],
            "role_scope": proof,
            "page_no": 1,
            "region_id": "controlled-source-region",
        }
        with tempfile.TemporaryDirectory(prefix="role-grid-carrier-") as temporary:
            path = Path(temporary) / "source.json"
            write_json_atomic(path, record, shared=True)
            saved = load_json(path, {})
        self.assertEqual(saved, record)
        self.assertTrue(valid_role_scope(saved))
        self.assertEqual(
            [item["identifier"] for item in identifier_references(saved)], identifiers
        )

    def test_normal_grid_discovery_retains_all_large_original_reference_rows(self):
        from patent_sar_extractor.core.binding_source_regions import reference_regions

        page, _grid, tokens, identifiers = self.original(32)
        with patch(
            "patent_sar_extractor.core.activity_grid_role_observation.get_ocr_engine",
            side_effect=AssertionError(
                "Fully native discovered grid must not invoke OCR"
            ),
        ):
            regions = reference_regions(
                page, original_pdf_sha256="a" * 64, tokens=tokens
            )
        self.assertEqual(len(regions), 1)
        self.assertTrue(valid_role_scope(regions[0]))
        self.assertEqual(
            [item["identifier"] for item in identifier_references(regions[0])],
            identifiers,
        )
