"""Reference versions remain exactly typed across shared source/QA contracts."""

import unittest

from patent_sar_extractor.contracts import (
    artifact_identity,
    artifact_identity_matches,
    schema_ref_matches,
)


class ContractVersionTypeTests(unittest.TestCase):
    def test_bool_float_string_and_extra_fields_do_not_become_integer_versions(self):
        expected = {"name": "patentsar.controlled-schema", "version": 1}
        self.assertTrue(schema_ref_matches(expected, expected))
        for value in (True, 1.0, "1", None):
            self.assertFalse(
                schema_ref_matches({**expected, "version": value}, expected)
            )
        self.assertFalse(
            schema_ref_matches({**expected, "extra": "unproved"}, expected)
        )

    def test_complete_artifact_envelope_preserves_integer_version_type(self):
        payload = artifact_identity("patentsar.controlled-schema", 1)
        self.assertTrue(
            artifact_identity_matches(payload, "patentsar.controlled-schema", 1)
        )
        for value in (True, 1.0, "1"):
            changed = {**payload, "schema": {**payload["schema"], "version": value}}
            self.assertFalse(
                artifact_identity_matches(changed, "patentsar.controlled-schema", 1)
            )
