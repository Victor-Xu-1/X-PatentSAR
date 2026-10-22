"""The existing pair, serialization and original replayer consume physical children."""

import copy
import json
import unittest
from contextlib import nullcontext
from unittest.mock import patch

from patent_sar_extractor.artifact_catalog import expand_shared_json, pack_shared_json
from patent_sar_extractor.core.activity_auxiliary_replay import (
    original_activity_source_errors,
)
from patent_sar_extractor.core.activity_header_evidence import (
    proof_id,
    validate_header_evidence,
)
from patent_sar_extractor.core.activity_header_observation import refine_scanned_header
from patent_sar_extractor.core.activity_header_pair import observe_header_pair
from patent_sar_extractor.core.activity_header_proof import (
    valid_header_column,
    valid_header_proof,
)
from patent_sar_extractor.core.activity_headers import context_from_text, grid_schema
from tests import test_auxiliary_cell_evidence as auxiliary_fixture
from tests import test_header_grid_cell_rows as source_fixture


class HeaderGridConsumerTests(unittest.TestCase):
    observe = source_fixture.HeaderGridCellRowTests.observe

    def test_normal_refinement_composes_current_source_context_and_every_header_child(
        self,
    ):
        view = self.observe()
        original = grid_schema(
            context_from_text("Table 47. Binding assay"), view.matrix
        )
        self.assertEqual(original.first_data_row, 2)
        with (
            patch(
                "patent_sar_extractor.core.activity_header_columns.get_ocr_engine",
                return_value=("rapidocr", None),
            ),
            patch(
                "patent_sar_extractor.core.activity_header_columns.observe_original_cell",
                side_effect=self.literal_cell,
            ),
            patch(
                "patent_sar_extractor.core.activity_header_observation.ocr_tokens_with_positions",
                return_value=self.source_tokens,
            ),
            patch(
                "patent_sar_extractor.core.activity_header_pair.get_auxiliary_text_runtime",
                side_effect=AssertionError("Complete primaries need no auxiliary"),
            ),
        ):
            resolved = refine_scanned_header(
                self.document[0], self.region, original, tokens=self.source_tokens
            )
        self.assertEqual(resolved.header_resolution["column_contract"], 4)
        self.assertEqual(
            resolved.header_resolution["status"], "observed_header_consensus"
        )
        self.assertEqual(
            resolved.raw_headers, ("Compound\nNo.", "IC50\n(nM)", "Dmax\n(%)")
        )
        self.assertTrue(valid_header_proof(resolved.header_resolution))

    def pair(self, reader, *, weak=True, blank=False, mutate=None):
        original = [
            self.observe(dpi, weak_unit=weak, blank_id_row=blank) for dpi in (400, 600)
        ]
        if mutate is not None:
            mutate(original)
        before = copy.deepcopy(original)
        pending = list(original)
        with patch(
            "patent_sar_extractor.core.activity_header_pair.get_auxiliary_text_runtime",
            return_value=reader,
        ) as acquire:
            result = observe_header_pair(
                self.document[0],
                {"xs": [40, 140, 240, 350], "ys": [50, 78, 106, 134]},
                2,
                (),
                lambda *args: pending.pop(0),
            )
        self.assertEqual(
            original, before, "Refinement cannot overwrite raw primary observations"
        )
        return result, acquire

    def test_complete_and_proved_blank_columns_never_load_an_auxiliary_model(self):
        _pair, acquire = self.pair(None, weak=False, blank=True)
        acquire.assert_not_called()

    def test_only_weak_physical_child_uses_the_existing_paired_recovery(self):
        reader = auxiliary_fixture.ControlledAuxiliary(("(nM)",))
        result, _ = self.pair(reader)
        self.assertEqual(reader.calls, 2)
        for dpi, view in zip((400, 600), result):
            self.assertEqual(view.verified, (True, True, True))
            self.assertTrue(
                valid_header_column(
                    view.columns[1], 1, "IC50\n(nM)", [40, 50, 350, 106], dpi
                )
            )
            for index, owner in enumerate(view.columns):
                for row, child in enumerate(owner["header_cells"]):
                    self.assertEqual("auxiliary_text" in child, (index, row) == (1, 1))
        payload = {
            "header_observations": {
                "controlled": {
                    "page_no": 1,
                    "observations": [
                        {"columns": list(view.columns)} for view in result
                    ],
                }
            }
        }
        self.assertEqual(
            original_activity_source_errors(
                payload, open_original=lambda: nullcontext(self.document)
            ),
            [],
        )

    def test_off_or_below_quality_auxiliary_keeps_the_unresolved_child(self):
        result, _ = self.pair(None)
        self.assertFalse(result[0].verified[1])
        reader = auxiliary_fixture.ControlledAuxiliary(("(nM)",))
        original = reader.observe
        reader.observe = lambda image: {**original(image), "confidence": 0.98}
        result, _ = self.pair(reader)
        self.assertFalse(any(view.verified[1] for view in result))
        for view in result:
            child = view.columns[1]["header_cells"][1]
            self.assertEqual(child["raw_text"], "(nM)")
            self.assertEqual(
                child["auxiliary_attempt"]["code"], "unqualified_original_row"
            )

    def test_crossing_or_known_detector_conflict_cannot_be_rescued(self):
        for field in ("crosses_boundary", "detector_conflict"):
            reader = auxiliary_fixture.ControlledAuxiliary(("(nM)",))

            def mutate(views, field=field):
                for view in views:
                    owner = view.columns[1]
                    owner["header_cells"][1][field] = True
                    owner[field] = True

            result, _ = self.pair(reader, mutate=mutate)
            self.assertEqual(reader.calls, 0)
            self.assertFalse(any(view.verified[1] for view in result))

    def test_complete_serialized_header_uses_the_same_field_and_original_gates(self):
        pair, _ = self.pair(None, weak=False, blank=True)
        proof = {
            "column_contract": 1,
            "status": "observed_header_consensus",
            "page_no": 1,
            "original_headers": [],
            "original_context": "",
            "discovery_observations": [],
            "header_band_bbox": [40, 50, 350, 106],
            "conflicting_columns": [],
            "unverified_columns": [],
            "context_conflict": False,
            "observations": [
                {
                    "method": f"header_ocr_{dpi}dpi",
                    "bbox": [0, 0, 390, 50],
                    "matrix": view.matrix,
                    "prefix": "Table 47. Binding assay",
                    "columns": list(view.columns),
                }
                for dpi, view in zip((400, 600), pair)
            ],
        }
        self.assertTrue(valid_header_proof(proof))
        payload = {"header_observations": {proof_id(proof): proof}}
        restored = expand_shared_json(json.loads(json.dumps(pack_shared_json(payload))))
        self.assertEqual(restored, payload)
        self.assertEqual(validate_header_evidence(restored), [])
        self.assertEqual(
            original_activity_source_errors(
                restored, open_original=lambda: nullcontext(self.document)
            ),
            [],
        )
