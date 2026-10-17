"""A saved region cannot erase original source by shortening its body scope."""

import unittest

from test_unruled_structure_proof import region_section, rehash_region
from unruled_structure_support import UnruledStructureControls

from patent_sar_extractor.core.binding_source_references import reference_issues
from patent_sar_extractor.core.source_observations import project_source_observation


class UnruledBodyReplayTests(UnruledStructureControls, unittest.TestCase):
    def test_rehashed_truncated_body_cannot_hide_a_later_original_label_or_diagram(
        self,
    ):
        _, payload = self.run_binding(["73", "28", "901"])
        region = region_section(payload)["source"]
        region["body_bottom"] = 325
        region["labels"].pop()
        region["diagrams"].pop()
        for column in region["pair_sources"]:
            column["window"][3] = 325
            chunk = column["chunks"][0]
            box = [*chunk["bbox"][:3], 325]
            chunk["sources"] = [
                project_source_observation(source, box) for source in chunk["sources"]
            ]
            chunk["bbox"] = box
        rehash_region(payload)
        with self.assertRaisesRegex(ValueError, "body boundary differs"):
            reference_issues(payload, payload["compound_catalog"]["entries"])

    def test_owned_candidate_cannot_be_dropped_from_the_complete_page_projection(self):
        _, payload = self.run_binding(["73", "28"])
        region_section(payload)["source"]["diagrams"].pop()
        rehash_region(payload)
        with self.assertRaisesRegex(ValueError, "complete page scope"):
            reference_issues(payload, payload["compound_catalog"]["entries"])

    def test_identifier_column_cannot_change_a_token_retained_in_the_full_context(self):
        _, payload = self.run_binding(["73", "28"])
        region = region_section(payload)["source"]
        # The token still has the same text, confidence and valid own frame;
        # changing its original box must nevertheless fail parent conservation.
        region["pair_sources"][0]["chunks"][0]["sources"][0]["tokens"][0]["bbox"][
            0
        ] += 1
        rehash_region(payload)
        with self.assertRaisesRegex(ValueError, "projection differs"):
            reference_issues(payload, payload["compound_catalog"]["entries"])
