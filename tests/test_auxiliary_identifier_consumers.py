"""Numbered-source proofs must reach the same original and activity consumers."""

import copy
import json
import unittest
from contextlib import nullcontext
from unittest.mock import patch

from patent_sar_extractor.core.activity_auxiliary_replay import (
    auxiliary_columns,
    original_activity_source_errors,
)
from patent_sar_extractor.core.activity_grid_cells import read_activity_cell
from patent_sar_extractor.core.activity_result_references import _observed
from patent_sar_extractor.core.binding_original_replay import (
    original_binding_source_errors,
    original_binding_sources,
)
from tests import test_auxiliary_identifiers as identifier_fixture


class AuxiliaryIdentifierConsumerTests(unittest.TestCase):
    def setUp(self):
        fixture = identifier_fixture.AuxiliaryIdentifierTests()
        self.addCleanup(fixture.doCleanups)
        self.page, _, self.reading = fixture.read("Compound 41A", kind="label")
        self.assertFalse(self.reading.needs_review)
        self.cell = {
            "field": "compound_id",
            "value": "Compound 41A",
            "bbox": list(self.reading.bounds),
            "observations": self.reading.observations,
        }

    def test_bare_numbered_cell_requires_and_replays_original_pixels(self):
        bindings = [
            {
                "structure_id": "test-structure",
                "numbered_table_cell_evidence": {
                    "page_no": 1,
                    "observations": self.reading.observations,
                },
            }
        ]
        self.assertTrue(original_binding_sources(bindings))
        self.assertEqual(original_binding_source_errors(self.page.parent, bindings), [])
        self.page.insert_text((90, 45), "note", fontsize=8)
        self.assertTrue(original_binding_source_errors(self.page.parent, bindings))

    def test_activity_id_reading_preserves_literal_prefix_without_false_crossing(self):
        with patch(
            "patent_sar_extractor.core.activity_grid_cells.read_cell",
            return_value=self.reading,
        ):
            value, _, review = read_activity_cell(
                self.page, [], self.reading.bounds, identifier=True, native=False
            )
        self.assertEqual(value, "Compound 41A")
        self.assertFalse(review)
        self.assertTrue(_observed(self.cell, identifier=True))

    def test_activity_accepted_and_unresolved_rows_replay_their_original_id_cells(self):
        for payload in (
            {"rows": [{"activity_sources": [{"page_no": 1, "cells": [self.cell]}]}]},
            {"unresolved_rows": [{"page_no": 1, "cells": [self.cell]}]},
        ):
            with self.subTest(payload=list(payload)):
                restored = json.loads(json.dumps(payload))
                self.assertEqual(len(list(auxiliary_columns(restored))), 1)
                self.assertTrue(original_activity_source_errors(restored))
                self.assertEqual(
                    original_activity_source_errors(
                        restored, open_original=lambda: nullcontext(self.page.parent)
                    ),
                    [],
                )
        self.page.insert_text((90, 45), "note", fontsize=8)
        self.assertTrue(
            original_activity_source_errors(
                payload, open_original=lambda: nullcontext(self.page.parent)
            )
        )

    def test_activity_scalar_or_identifier_cannot_drop_auxiliary_source_proof(self):
        for identifier in (True, False):
            cell = copy.deepcopy(self.cell)
            cell["observations"][-1].pop("auxiliary_text")
            self.assertFalse(_observed(cell, identifier=identifier))

    def test_same_observation_identity_cannot_acquire_a_second_literal(self):
        cell = copy.deepcopy(self.cell)
        fixture = identifier_fixture.AuxiliaryIdentifierTests()
        self.addCleanup(fixture.doCleanups)
        _page, _runtime, observed = fixture.read("Compound 41B", kind="label")
        cell["value"] = "41B"
        cell["observations"] = observed.observations
        payload = {
            "rows": [{"activity_sources": [{"page_no": 1, "cells": [self.cell, cell]}]}]
        }
        with self.assertRaisesRegex(ValueError, "conflicting outputs"):
            list(auxiliary_columns(payload))
