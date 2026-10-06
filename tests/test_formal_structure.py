"""Single catalog-reader delegation, immutable source input and coverage types."""

from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from patent_sar_extractor.core.formal_structure import (
    binding_pairs,
    coverage_errors,
    proved_catalog,
)
from tests.test_source_led_export import run_fixture


class FormalStructureTests(unittest.TestCase):
    def test_catalog_reader_is_sole_source_proof_authority(self):
        payload = {"compound_catalog": {"controlled": True}}
        known = {"S1"}
        with patch(
            "patent_sar_extractor.core.formal_structure.read_catalog_entries",
            return_value=([{"cpd": "Compound 42"}], set()),
        ) as reader:
            self.assertEqual(proved_catalog(payload, known), [{"cpd": "Compound 42"}])
        reader.assert_called_once_with(payload, known)

    def test_current_exact_catalog_validation_does_not_mutate_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_fixture(root)
            import json

            payload = json.loads(
                (root / "structure_bindings/bindings.json").read_text()
            )
            before = copy.deepcopy(payload)
            self.assertEqual(coverage_errors(payload), [])
            self.assertEqual(payload, before)

    def test_old_or_unknown_parent_identity_hard_fails(self):
        with self.assertRaises(ValueError):
            coverage_errors({"final_bindings": []})

    def test_malformed_identifier_types_are_not_string_guessed(self):
        for rows in (
            [{"cpd": {"guess": 42}, "structure_id": "S1"}],
            [{"cpd": "Compound 42", "structure_id": 42}],
            [{"cpd": "", "structure_id": "S1"}],
        ):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                binding_pairs(rows)


if __name__ == "__main__":
    unittest.main()
