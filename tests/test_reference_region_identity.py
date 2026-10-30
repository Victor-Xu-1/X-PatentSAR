"""Large grid identities retain bounded cells and replay their complete source."""

import copy
import hashlib
import json
import unittest
from unittest.mock import patch

from patent_sar_extractor.core.binding_source_references import (
    _regions,
    reference_scope,
)
from patent_sar_extractor.core.binding_source_regions import reference_regions
from patent_sar_extractor.core.reference_region_identity import reference_region_id
from patent_sar_extractor.core.source_evidence_identity import (
    SourceEvidenceLimit,
    proof_id,
)
from tests import test_role_grid_coverage as grid_controls


class ReferenceRegionIdentityTests(unittest.TestCase):
    def region(self):
        fixture = grid_controls.RoleGridCoverageTests()
        self.addCleanup(fixture.doCleanups)
        page, grid, tokens, _ = fixture.original(2)
        return reference_regions(
            page, original_pdf_sha256="a" * 64, grids=[grid], tokens=tokens
        )[0]

    def test_small_region_keeps_the_existing_canonical_identity(self):
        region = self.region()
        record = {key: value for key, value in region.items() if key != "region_id"}
        self.assertEqual(reference_region_id(record), proof_id(record))
        section = {
            "role": "characterization_region",
            "page_no": 1,
            "source_region": region,
        }
        scope = reference_scope([section], original_pdf_sha256="a" * 64)
        self.assertEqual(_regions([section], scope), {region["region_id"]: region})

    def test_complete_region_and_each_cell_have_independent_finite_budgets(self):
        region = self.region()
        record = {key: value for key, value in region.items() if key != "region_id"}
        encoded = json.dumps(
            record,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        with patch(
            "patent_sar_extractor.core.reference_region_identity.MAX_REGION_BYTES",
            len(encoded),
        ):
            self.assertEqual(
                reference_region_id(record), hashlib.sha256(encoded).hexdigest()
            )
        with (
            patch(
                "patent_sar_extractor.core.reference_region_identity.MAX_REGION_BYTES",
                len(encoded) - 1,
            ),
            self.assertRaisesRegex(SourceEvidenceLimit, "region exceeds"),
        ):
            reference_region_id(record)
        with (
            patch(
                "patent_sar_extractor.core.reference_region_identity.MAX_COMPONENT_BYTES",
                64,
            ),
            self.assertRaisesRegex(SourceEvidenceLimit, "component exceeds"),
        ):
            reference_region_id(record)

    def test_modified_cell_cannot_reuse_or_rehash_the_saved_original(self):
        region = self.region()
        changed = copy.deepcopy(region)
        changed["role_scope"]["observations"][0]["cells"][3]["text"] = "123456"
        section = {
            "role": "characterization_region",
            "page_no": 1,
            "source_region": changed,
        }
        scope = reference_scope([section], original_pdf_sha256="a" * 64)
        with self.assertRaises(ValueError):
            _regions([section], scope)
        record = {key: value for key, value in changed.items() if key != "region_id"}
        with self.assertRaises(ValueError):
            reference_region_id(record)


if __name__ == "__main__":
    unittest.main()
