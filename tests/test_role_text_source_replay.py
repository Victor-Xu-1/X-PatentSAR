"""Known role-source owners must not disappear from original text replay.

These are literal source-carrier controls, not a grant of characterization roles
to the fixture's assay words and not an OCR/scientific accuracy claim.
"""

import copy
import unittest
from contextlib import nullcontext
from unittest.mock import patch

from patent_sar_extractor.core.activity_auxiliary_replay import (
    auxiliary_columns,
    original_activity_source_errors,
)
from patent_sar_extractor.core.binding_original_replay import (
    original_binding_source_errors,
    original_binding_sources,
)
from patent_sar_extractor.core.ocsr.recognition_inputs import (
    RecognitionPlan,
    recognition_inputs,
)
from patent_sar_extractor.core.source_role_observations import (
    role_failure,
    scope_observations,
    serialize_role_observations,
)
from patent_sar_extractor.core.text_ocr.cell_capture import refine_text_pair
from tests import test_auxiliary_cell_evidence as controls
from tests import test_candidate_observations as candidate_controls
from tests.test_web_acceptance import complete_payloads


class RoleTextSourceReplayTests(unittest.TestCase):
    def setUp(self):
        self.source = controls.AuxiliaryCellEvidenceTests()
        self.source.setUp()
        self.addCleanup(self.source.doCleanups)
        pair = refine_text_pair(
            self.source.images, self.source.primaries, controls.ControlledAuxiliary()
        )
        self.assertIsNotNone(pair)
        x0, y0, x1, y1 = self.source.bounds
        self.cells = {
            "xs": [x0, x1],
            "ys": [y0, y1],
            "native_hints": [[""]],
            "observations": [
                {
                    "method": reading["method"],
                    "matrix": [[reading["text"]]],
                    "cells": [reading],
                }
                for reading in pair
            ],
        }

    def diagnostic(self, *, source_sha=""):
        failure = role_failure(
            "unqualified_role_observations",
            self.cells,
            "Original unknown table",
            self.cells,
        )
        return {
            "source_role_observations": serialize_role_observations(
                scope_observations([failure], 1, original_pdf_sha256=source_sha)
            ),
            "rows": [],
            "header_observations": {},
        }

    def test_unresolved_role_cells_still_require_the_actual_original(self):
        errors = original_activity_source_errors(self.diagnostic())
        self.assertTrue(
            any("Original PDF is required" in error for error in errors), errors
        )

    def test_changed_original_role_pixels_refuse_without_read_side_inference(self):
        payload = self.diagnostic()
        with patch(
            "patent_sar_extractor.core.text_ocr.source_capture.get_auxiliary_text_runtime",
            side_effect=AssertionError("Original replay must never invoke a model"),
        ):
            self.assertEqual(
                original_activity_source_errors(
                    payload, open_original=lambda: nullcontext(self.source.document)
                ),
                [],
            )
            self.source.page.insert_text((30, 76), "pM", fontsize=6)
            self.assertTrue(
                original_activity_source_errors(
                    payload, open_original=lambda: nullcontext(self.source.document)
                )
            )

    def test_coverage_role_owner_cannot_hide_its_selected_text_observations(self):
        payload = {
            "coverage": {
                "regions": [{"page_no": 1, "role_scope": copy.deepcopy(self.cells)}]
            },
            "rows": [],
            "header_observations": {},
        }
        self.assertTrue(original_activity_source_errors(payload))

    def test_a_native_role_source_does_not_load_auxiliary_ocr(self):
        from patent_sar_extractor.core.activity_grid_role_observation import (
            observe_characterization,
        )
        from tests import test_role_grid_coverage as native_controls

        fixture = native_controls.RoleGridCoverageTests()
        self.addCleanup(fixture.doCleanups)
        page, grid, tokens, _ids = fixture.original(1)
        scope = observe_characterization(
            page, grid, tokens, "Table J. Compound characterization"
        )
        payload = {"coverage": {"regions": [{"page_no": 1, "role_scope": scope}]}}
        with patch(
            "patent_sar_extractor.core.text_ocr.source_capture.get_auxiliary_text_runtime",
            side_effect=AssertionError(
                "Native source reads must not load auxiliary OCR"
            ),
        ):
            self.assertTrue(original_activity_source_errors(payload))
            self.assertEqual(
                original_activity_source_errors(
                    payload, open_original=lambda: nullcontext(page.parent)
                ),
                [],
            )

    def test_same_packet_in_known_role_owners_is_replayed_once(self):
        payload = self.diagnostic()
        payload["coverage"] = {"regions": [{"page_no": 1, "role_scope": self.cells}]}
        payload["source_sections"] = [
            {
                "role": "characterization_region",
                "source_region": {"page_no": 1, "role_scope": self.cells},
            }
        ]
        self.assertEqual(len(list(auxiliary_columns(payload))), 1)

    def test_auxiliary_packet_cannot_borrow_a_different_physical_role_cell(self):
        payload = self.diagnostic()
        source = next(iter(payload["source_role_observations"].values()))[
            "source_cells"
        ]
        source["xs"] = [self.source.bounds[0] + 1, self.source.bounds[2]]
        with self.assertRaisesRegex(ValueError, "original role cell"):
            list(auxiliary_columns(payload))

    def test_binding_source_plan_retains_role_text_for_original_replay_only(self):
        payload = complete_payloads()["bindings"]
        payload["source_role_observations"] = self.diagnostic(
            source_sha=payload["source_reference_scope"]["original_pdf_sha256"]
        )["source_role_observations"]
        plan = recognition_inputs(payload)
        self.assertEqual(len(plan.role_text), 1)
        self.assertTrue(original_binding_sources([], role_text=plan.role_text))
        self.assertEqual(
            original_binding_source_errors(
                self.source.document, [], role_text=plan.role_text
            ),
            [],
        )
        self.source.page.insert_text((30, 76), "pM", fontsize=6)
        self.assertTrue(
            original_binding_source_errors(
                self.source.document, [], role_text=plan.role_text
            )
        )

    def test_candidate_path_resolution_cannot_drop_role_text_or_recognize_it_as_a_molecule(
        self,
    ):
        fixture = candidate_controls.CandidateObservationTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        role_text = tuple(auxiliary_columns(self.diagnostic()))
        original = RecognitionPlan([fixture.owner], [], [], role_text=role_text)
        plan = fixture.plan(sources=original)
        self.assertEqual(plan.proven.role_text, role_text)
        self.assertEqual(len(plan.work_items), 1)
        self.assertEqual(len(plan.inventory["entries"]), 2)
        self.assertEqual(len(plan.proven.work_items), 1)
