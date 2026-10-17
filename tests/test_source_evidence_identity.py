"""The established canonical source digest must remain byte-compatible."""

import hashlib
import json
import unittest

from patent_sar_extractor.core.source_evidence_identity import proof_id


class SourceEvidenceIdentityTests(unittest.TestCase):
    def test_existing_canonical_utf8_digest_is_unchanged(self):
        proof = {
            "status": "observed_original",
            "编号": "I-003B",
            "bbox": [0, 1.5, 20, 30],
        }
        expected = hashlib.sha256(
            json.dumps(
                proof,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        self.assertEqual(proof_id(proof), expected)
        self.assertEqual(proof_id(proof), proof_id(dict(reversed(list(proof.items())))))

    def test_missing_or_untyped_status_is_not_an_original_evidence_root(self):
        for proof in (None, [], {}, {"status": True}):
            with self.subTest(proof=proof), self.assertRaises(TypeError):
                proof_id(proof)

    def test_nonfinite_values_cannot_enter_a_source_digest(self):
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                proof_id({"status": "observed_original", "value": value})

    def test_the_existing_one_mib_bound_refuses_instead_of_truncating(self):
        with self.assertRaises(ValueError):
            proof_id({"status": "observed_original", "text": "x" * (1024 * 1024)})
