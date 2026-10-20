"""Generated ordinary role sources must remain tied to the actual original PDF.

Read-only diagnosis of current source code; no private inputs, product changes,
model execution or scientific results are created by this control.
"""

import copy
import unittest
from contextlib import nullcontext
from unittest.mock import patch

import fitz

from patent_sar_extractor.core.activity_auxiliary_replay import (
    original_activity_source_errors,
)
from patent_sar_extractor.core.activity_grid_role_proof import valid_role_scope
from tests import test_role_grid_coverage as native
from tests import test_role_text_recovery as raster


class PrimaryRoleReplayTests(unittest.TestCase):
    def test_native_blank_requires_original_empty_grid_pixels_not_only_missing_text(
        self,
    ):
        from patent_sar_extractor.core.activity_grid_role_observation import (
            observe_role_cells,
        )
        from patent_sar_extractor.core.role_original_replay import (
            original_role_source_errors,
        )
        from patent_sar_extractor.core.source_geometry import (
            SourceTokens,
            source_layout,
        )

        with fitz.open() as document:
            page = document.new_page(width=180, height=100)
            for x in (10, 80, 150):
                page.draw_line((x, 10), (x, 50))
            for y in (10, 50):
                page.draw_line((10, y), (150, y))
            page.insert_text((20, 32), "NMR", fontsize=9)
            layout = source_layout(page)
            cells = observe_role_cells(
                page,
                {"xs": [10, 80, 150], "ys": [10, 50]},
                SourceTokens(layout.native, layout),
            )
            blank = cells["observations"][0]["cells"][1]
            self.assertEqual(blank["method"], "native_cell")
            self.assertEqual(blank["text"], "")
            self.assertEqual(original_role_source_errors(document, [(1, blank)]), [])
            page.draw_line((95, 25), (125, 40), width=1)
            self.assertTrue(original_role_source_errors(document, [(1, blank)]))

    def test_current_native_role_cannot_drop_its_complete_source_observation(self):
        page, payload = self.source("native")
        scope = payload["coverage"]["regions"][0]["role_scope"]
        for reading in scope["observations"][0]["cells"]:
            self.assertEqual(reading["source_observation"]["schema_version"], 2)
            del reading["source_observation"]
        self.assertTrue(
            original_activity_source_errors(
                payload, open_original=lambda: nullcontext(page.parent)
            )
        )

    def source(self, method):
        if method == "native":
            fixture = native.RoleGridCoverageTests()
            self.addCleanup(fixture.doCleanups)
            page, grid, tokens, _ids = fixture.original(1)
            from patent_sar_extractor.core.activity_grid_role_observation import (
                observe_characterization,
            )

            proof = observe_characterization(
                page, grid, tokens, "Table J. Compound characterization"
            )
        else:
            fixture = raster.RoleTextRecoveryTests()
            self.addCleanup(fixture.doCleanups)
            page, grid, proof, failures, reader, runtime = fixture.observe(
                qualified=True
            )
            self.assertEqual(failures, [])
            self.assertEqual(reader.calls, 0)
            runtime.assert_not_called()
        record = {
            "page_no": 1,
            "bbox": [grid["xs"][0], grid["ys"][0], grid["xs"][-1], grid["ys"][-1]],
            "role_scope": copy.deepcopy(proof),
        }
        self.assertTrue(valid_role_scope(record))
        return page, {
            "coverage": {"regions": [record]},
            "rows": [],
            "header_observations": {},
        }

    def test_complete_ordinary_role_requires_actual_original(self):
        for method in ("native", "raster"):
            with self.subTest(method=method):
                _page, payload = self.source(method)
                self.assertTrue(
                    original_activity_source_errors(payload),
                    "Known original role proof cannot bypass required original PDF replay",
                )

    def test_changed_original_cannot_retain_a_qualified_saved_role(self):
        for method in ("native", "raster"):
            with self.subTest(method=method):
                page, payload = self.source(method)
                self.assertEqual(
                    original_activity_source_errors(
                        payload,
                        open_original=lambda page=page: nullcontext(page.parent),
                    ),
                    [],
                )
                scope = payload["coverage"]["regions"][0]["role_scope"]
                page.insert_text(
                    (scope["xs"][-2] + 5, scope["ys"][-2] + 15),
                    "IC50 = 3 nM",
                    fontsize=6,
                )
                self.assertTrue(
                    original_activity_source_errors(
                        payload,
                        open_original=lambda page=page: nullcontext(page.parent),
                    ),
                    "Changed original role cell must not pass on saved role status",
                )

    def test_model_free_readback_and_missing_or_changed_frame_refusal(self):
        page, payload = self.source("raster")
        with (
            patch(
                "patent_sar_extractor.core.activity_grid_role_observation.get_ocr_engine",
                side_effect=AssertionError("Readback cannot load ordinary OCR"),
            ),
            patch(
                "patent_sar_extractor.core.text_ocr.source_capture.get_auxiliary_text_runtime",
                side_effect=AssertionError("Readback cannot load auxiliary OCR"),
            ),
        ):
            self.assertEqual(
                original_activity_source_errors(
                    payload, open_original=lambda: nullcontext(page.parent)
                ),
                [],
            )
            for mutation in ("missing", "hash", "shape", "bounds"):
                changed = copy.deepcopy(payload)
                record = changed["coverage"]["regions"][0]
                cell = record["role_scope"]["observations"][0]["cells"][-1]
                if mutation == "missing":
                    del cell["source_frame"]
                elif mutation == "hash":
                    cell["source_frame"]["pixel_sha256"] = "f" * 64
                elif mutation == "shape":
                    cell["source_frame"]["shape"][0] -= 1
                else:
                    cell["bbox"][0] += 1
                if mutation == "bounds":
                    with self.assertRaisesRegex(ValueError, "original role cell"):
                        original_activity_source_errors(
                            changed, open_original=lambda: nullcontext(page.parent)
                        )
                else:
                    self.assertTrue(
                        original_activity_source_errors(
                            changed, open_original=lambda: nullcontext(page.parent)
                        )
                    )
                if mutation in ("missing", "bounds"):
                    self.assertFalse(valid_role_scope(record))

    def test_binding_plan_keeps_all_ordinary_sources_separate_from_molecule_work(self):
        from patent_sar_extractor.core.binding_original_replay import (
            original_binding_source_errors,
            original_binding_sources,
        )
        from patent_sar_extractor.core.ocsr.recognition_inputs import recognition_inputs
        from patent_sar_extractor.core.source_role_observations import (
            role_failure,
            scope_observations,
            serialize_role_observations,
        )
        from tests.test_web_acceptance import complete_payloads

        for method, count in (("native", 6), ("raster", 12)):
            with self.subTest(method=method):
                page, source = self.source(method)
                payload = complete_payloads()["bindings"]
                scope = source["coverage"]["regions"][0]["role_scope"]
                cells = {
                    key: scope[key]
                    for key in ("xs", "ys", "native_hints", "observations")
                }
                failure = role_failure(
                    "unqualified_role_observations", cells, scope["prefix"], cells
                )
                sha = payload["source_reference_scope"]["original_pdf_sha256"]
                payload["source_role_observations"] = serialize_role_observations(
                    scope_observations([failure], 1, original_pdf_sha256=sha)
                )
                before = recognition_inputs(complete_payloads()["bindings"])
                plan = recognition_inputs(payload)
                self.assertEqual(len(plan.role_text), count)
                self.assertEqual(len(plan.work_items), len(before.work_items))
                self.assertTrue(original_binding_sources([], role_text=plan.role_text))
                self.assertEqual(
                    original_binding_source_errors(
                        page.parent, [], role_text=plan.role_text
                    ),
                    [],
                )
                page.insert_text(
                    (scope["xs"][-2] + 5, scope["ys"][-2] + 15),
                    "IC50 = 3 nM",
                    fontsize=6,
                )
                self.assertTrue(
                    original_binding_source_errors(
                        page.parent, [], role_text=plan.role_text
                    )
                )

    def test_duplicate_known_owners_do_not_drop_distinct_views_or_borrow_pages(self):
        from patent_sar_extractor.core.role_text_sources import role_text_cells

        for method, count in (("native", 6), ("raster", 12)):
            with self.subTest(method=method):
                _page, payload = self.source(method)
                record = payload["coverage"]["regions"][0]
                payload["source_sections"] = [
                    {
                        "role": "characterization_region",
                        "source_region": copy.deepcopy(record),
                    }
                ]
                self.assertEqual(len(list(role_text_cells(payload))), count)
                payload["source_sections"][0]["source_region"]["page_no"] = 2
                self.assertEqual(len(list(role_text_cells(payload))), count * 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
