"""Existing OCR on controlled original raster catalogues and native shadows."""

import copy
import json
import unittest

import fitz

from patent_sar_extractor.core.caption_binding_proof import (
    valid_caption_binding_evidence,
)
from patent_sar_extractor.core.caption_grid_binding import bind_caption_grids
from patent_sar_extractor.core.caption_role_observation import observe_caption_role
from patent_sar_extractor.core.caption_role_proof import caption_role_status
from patent_sar_extractor.core.source_cell_claims import cell_source_status
from patent_sar_extractor.core.table_geometry import (
    detect_ruled_table_regions,
    page_tokens,
)
from tests.test_caption_source_roles import catalog


def raster_catalog(title="Table 47. Compounds", *, shadow=None, prefixed=False):
    original, structures, boxes = catalog(title, prefixed=prefixed)
    with original:
        pixmap = original[0].get_pixmap(matrix=fitz.Matrix(3, 3), alpha=False)
    doc = fitz.open()
    page = doc.new_page()
    page.insert_image(page.rect, stream=pixmap.tobytes("png"))
    if shadow:
        page.insert_text((50, 85), shadow, fontsize=10, render_mode=3)
    return doc, structures, boxes


class CaptionRoleRasterTests(unittest.TestCase):
    def test_original_raster_title_and_number_rows_have_real_independent_readings(self):
        doc, structures, boxes = raster_catalog()
        with doc:
            result = bind_caption_grids(doc, structures, boxes, [1])
        self.assertEqual(
            [pair["label"] for pair in result.bindings],
            ["I-004A", "I-009B"],
            result.issues,
        )
        for pair in result.bindings:
            observed = json.loads(json.dumps(pair["observations"]))
            self.assertTrue(any(o["method"] == "cell_ocr_400dpi" for o in observed))
            self.assertTrue(
                any(o["method"] == "cell_ocr_600dpi" for o in observed)
                or any(
                    o["method"] == "page_ocr_cell"
                    and cell_source_status(o) == "qualified"
                    for o in observed
                )
            )
            role = pair["ownership"]["caption_role"]
            self.assertEqual(
                caption_role_status(role, 1, list(pair["label_bbox"])), "compound"
            )
            self.assertTrue(role["sources"])
            item = {
                "cpd": f"Compound {pair['label']}",
                "structure_id": pair["structure"]["id"],
                "page_no": 1,
                **{
                    f"struct_{axis}": pair["structure"][axis]
                    for axis in ("x0", "y0", "x1", "y1")
                },
                "exact_caption_evidence": {
                    "page_no": 1,
                    "bbox": list(pair["label_bbox"]),
                    "observations": observed,
                    "ownership": pair["ownership"],
                },
            }
            self.assertTrue(valid_caption_binding_evidence(item))

    def test_known_native_table_identity_or_role_cannot_be_outvoted_by_raster(self):
        for shadow in ("Table 48. Compounds", "Table 47. Intermediates"):
            with self.subTest(shadow=shadow):
                doc, structures, boxes = raster_catalog(shadow=shadow)
                with doc:
                    result = bind_caption_grids(doc, structures, boxes, [1])
                self.assertEqual(result.bindings, [])
                self.assertTrue(result.issues)

    def test_prefixed_labels_cannot_bypass_a_known_original_catalogue_conflict(self):
        for shadow in ("Table 48. Compounds", "Table 47. Intermediates"):
            with self.subTest(shadow=shadow):
                doc, structures, boxes = raster_catalog(shadow=shadow, prefixed=True)
                with doc:
                    result = bind_caption_grids(doc, structures, boxes, [1])
                self.assertEqual(result.bindings, [])
                self.assertEqual(result.exclusions, [])
                self.assertTrue(result.issues)

    def test_original_source_packet_cannot_omit_or_change_title_after_serialization(
        self,
    ):
        doc, _structures, _boxes = raster_catalog()
        with doc:
            page = doc[0]
            grids = detect_ruled_table_regions(page, dpi=240)
            tokens = page_tokens(page, dpi=200, allow_tesseract=False)
            scope = observe_caption_role(page, grids[0], grids, tokens)
        scope = json.loads(json.dumps(scope))
        xs, ys = grids[0]["xs"], grids[0]["ys"]
        cell = [xs[0], ys[0], xs[1], ys[1]]
        self.assertEqual(caption_role_status(scope, 1, cell), "compound")
        for field, value in (
            ("sources", []),
            ("observations", []),
            ("table_key", "TABLE48"),
        ):
            with self.subTest(field=field):
                changed = copy.deepcopy(scope)
                changed[field] = value
                self.assertIsNone(caption_role_status(changed, 1, cell))
