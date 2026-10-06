"""Workflow uses persisted order rather than inferred or historical success."""

import unittest

from patent_sar_extractor.contracts import CORE_STAGE_ORDER
from patent_sar_extractor.web.models import STAGES
from patent_sar_extractor.web.stages import stages_from_summary


class ActualStageOrderTests(unittest.TestCase):
    def test_persisted_source_order_drives_stage_projection(self):
        stages = stages_from_summary(
            {"steps": {}, "main_chain": list(CORE_STAGE_ORDER)}
        )
        self.assertEqual(tuple(s.name for s in stages), CORE_STAGE_ORDER)

    def test_historical_missing_order_is_not_rewritten(self):
        stages = stages_from_summary({"steps": {}})
        self.assertEqual(tuple(s.name for s in stages), STAGES)

    def test_invalid_or_duplicate_order_is_not_trusted(self):
        stages = stages_from_summary({"steps": {}, "main_chain": ["bind"] * 8})
        self.assertEqual(tuple(s.name for s in stages), STAGES)
