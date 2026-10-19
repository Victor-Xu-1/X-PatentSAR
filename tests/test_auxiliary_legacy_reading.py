"""Historical V1 packets stay readable; only V2 is produced by the live adapter."""

import copy
import unittest

from patent_sar_extractor.core.text_ocr.cell_capture import refine_text_pair
from patent_sar_extractor.core.text_ocr.cell_frames import source_rows
from patent_sar_extractor.core.text_ocr.cell_proof import (
    effective_cells,
    replay_auxiliary_cell,
)
from patent_sar_extractor.core.text_ocr.identity import recipe
from tests import test_auxiliary_cell_evidence as fixture_module


class LegacyAuxiliaryReadingTests(unittest.TestCase):
    def test_legacy_original_packet_remains_read_only_and_pixel_bound(self):
        fixture = fixture_module.AuxiliaryCellEvidenceTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        reader, views = fixture_module.ControlledAuxiliary(), []
        for dpi, image, primary in zip((400, 600), fixture.images, fixture.primaries):
            source = source_rows(image, dpi)
            views.append(
                {
                    **{
                        k: v
                        for k, v in source.items()
                        if k not in {"images", "row_bounds"}
                    },
                    "dpi": dpi,
                    "primary": copy.deepcopy(primary),
                    "rows": [
                        {"bbox": box, "observation": reader.observe(row)}
                        for box, row in zip(source["row_bounds"], source["images"])
                    ],
                }
            )
        spec = recipe()
        packet = {
            "version": 1,
            "model": {
                "name": spec["model_name"],
                "revision": spec["model_revision"],
                "adapter_version": spec["adapter_version"],
                "fingerprint": "b" * 64,
            },
            "views": views,
        }
        saved = copy.deepcopy(packet)
        historical = effective_cells(packet)
        self.assertTrue(
            all(replay_auxiliary_cell(cell, fixture.page) for cell in historical)
        )
        self.assertEqual(packet, saved)
        current = refine_text_pair(
            fixture.images, fixture.primaries, fixture_module.ControlledAuxiliary()
        )
        self.assertEqual(current[0]["auxiliary_text"]["version"], 2)
        fixture.page.insert_text((30, 76), "new ink", fontsize=6)
        self.assertFalse(replay_auxiliary_cell(historical[0], fixture.page))
