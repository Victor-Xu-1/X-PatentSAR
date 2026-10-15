"""Source eligibility is not a replacement extraction/scientific authority."""

import json
import unittest

from patent_sar_extractor.web.lead_source import (
    blocked_assessment,
    source_acceptance,
    source_identity,
    source_ready,
)
from patent_sar_extractor.web.models import Acceptance


class LeadSourceTests(unittest.TestCase):
    def test_only_current_accepted_error_free_source_is_ready(self):
        for state in ("not_run", "historical", "failed", "accepted"):
            for errors in ([], ["Controlled incomplete source"]):
                with self.subTest(state=state, errors=errors):
                    decision = Acceptance(state=state, errors=errors)
                    self.assertEqual(
                        source_ready(decision), state == "accepted" and not errors
                    )
                    if not source_ready(decision):
                        packet = blocked_assessment(decision)
                        self.assertEqual(packet.status, "unranked")
                        self.assertIsNone(packet.rank)
                        self.assertIsNone(packet.score)
                        self.assertEqual(packet.components, {})

    def test_invalid_or_missing_cached_authority_is_historical_not_success(self):
        for snapshot in (
            None,
            3,
            "{",
            "[]",
            "null",
            "{}",
            '{"acceptance":{"state":"accepted","errors":[1]}}',
            '{"acceptance":{"state":"unknown"}}',
            " " * (32 * 1024 * 1024 + 1),
        ):
            with self.subTest(kind=type(snapshot).__name__):
                decision = source_acceptance({"snapshot": snapshot})
                self.assertEqual(decision.state, "historical")
                self.assertFalse(source_ready(decision))
                self.assertTrue(decision.errors)

    def test_cached_valid_state_and_explicit_live_decision_keep_distinct_identity(self):
        project = {
            "snapshot": json.dumps({"acceptance": {"state": "accepted", "errors": []}})
        }
        self.assertTrue(source_ready(source_acceptance(project)))
        original = source_identity(project)
        failed = Acceptance(state="failed", errors=["Controlled source rejection"])
        self.assertNotEqual(source_identity(project, failed), original)
        self.assertEqual(source_identity(project), original)
