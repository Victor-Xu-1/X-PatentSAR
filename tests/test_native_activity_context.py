"""Actual generated native tables retain original headers and conditions."""

import io
import unittest
from contextlib import nullcontext
from dataclasses import asdict

import fitz
from PIL import Image

from patent_sar_extractor.core.activity_auxiliary_replay import (
    original_activity_source_errors,
)
from patent_sar_extractor.core.activity_coordinates import extract_coordinate_tables


class NativeActivityContextTests(unittest.TestCase):
    def setUp(self):
        self.document = fitz.open()
        self.addCleanup(self.document.close)
        self.page = self.document.new_page(width=450, height=300)

    def table(self, *, transposed=False):
        page = self.page
        page.insert_text((40, 65), "Table 3", fontsize=10)
        page.insert_text((40, 85), "Target: IRF5; Assay: binding", fontsize=10)
        for y in (110, 135, 160):
            page.draw_line((40, y), (350, y))
        for x in (40, 160, 350):
            page.draw_line((x, 110), (x, 160))
        cells = (
            ((170, 128, "Compound 1"), (50, 153, "IC50 (nM)"), (170, 153, "0.4"))
            if transposed
            else (
                (50, 128, "Compound ID"),
                (170, 128, "IC50 (nM)"),
                (50, 153, "1"),
                (170, 153, "0.4"),
            )
        )
        for x, y, text in cells:
            page.insert_text((x, y), text, fontsize=10)
        parsed = extract_coordinate_tables(self.document, [0])
        self.assertEqual(len(parsed.rows), 1)
        self.assertFalse(parsed.rows[0].needs_review)
        return {
            "coverage": {"regions": parsed.coverage},
            "rows": [asdict(row) for row in parsed.rows],
        }

    def check(self, payload):
        return original_activity_source_errors(
            payload, open_original=lambda: nullcontext(self.document)
        )

    def cover(self, bounds):
        self.page.draw_rect(fitz.Rect(bounds), color=None, fill=(1, 1, 1))

    def test_generic_native_header_is_retained_and_replayed_without_ocr(self):
        payload = self.table()
        self.assertEqual(self.check(payload), [])
        region = next(r for r in payload["coverage"]["regions"] if r.get("layout"))
        self.assertIsInstance(region["layout"].get("original_source"), dict)
        self.cover([165, 112, 300, 133])
        self.assertTrue(
            self.check(payload), "Unchanged values cannot excuse a hidden metric"
        )

    def test_native_experimental_context_is_not_just_saved_caption_text(self):
        payload = self.table()
        self.assertEqual(self.check(payload), [])
        self.cover([35, 70, 350, 90])
        self.assertTrue(
            self.check(payload), "Conditions must remain actual visible original claims"
        )

    def test_transposed_metric_header_and_context_use_the_same_original_gate(self):
        payload = self.table(transposed=True)
        self.assertEqual(self.check(payload), [])
        self.cover([45, 138, 150, 158])
        self.assertTrue(
            self.check(payload), "A row-name metric is not a measured-value cell"
        )

    def mixed_context(self, *, missing_target=False):
        from patent_sar_extractor.core.activity_header_sources import (
            capture_header_sources,
        )
        from patent_sar_extractor.core.source_geometry import (
            SourceTokens,
            source_layout,
        )

        image = io.BytesIO()
        Image.new("RGB", (450, 300), "white").save(image, format="PNG")
        self.page.insert_image(self.page.rect, stream=image.getvalue())
        self.page.insert_text((40, 65), "Table 3", fontsize=10, render_mode=3)
        self.page.insert_text(
            (40, 85), "Target: IRF5; Assay: binding", fontsize=10, render_mode=3
        )
        layout = source_layout(self.page)
        # Controlled raster tokens exercise the role contract only. This is
        # not a scientific OCR or full header-consensus acceptance claim.
        raster = [
            {
                **{k: v for k, v in token.items() if k != "native_paint"},
                "source": "raster",
                "confidence": 0.99,
            }
            for token in layout.native
            if not missing_target or token["y"] < 70
        ]
        tokens = SourceTokens(raster, layout, layout.raster_bounds)
        region = {"xs": [40, 160, 350], "ys": [110, 135, 160]}
        snapshot = capture_header_sources(self.page, region, 1, tokens)
        proof = {
            "page_no": 1,
            "header_band_bbox": [40, 110, 350, 135],
            "resolved_context": "Table 3\nTarget: IRF5; Assay: binding",
            "original_source": snapshot,
        }
        return {"header_observations": {"controlled-scope": proof}}

    def test_nonvisible_independent_layer_is_not_a_second_positive_context_vote(self):
        self.assertEqual(self.check(self.mixed_context()), [])

    def test_invisible_layer_cannot_fill_missing_experimental_conditions(self):
        self.assertTrue(self.check(self.mixed_context(missing_target=True)))

    def test_self_consistent_saved_metric_cannot_rename_the_original_endpoint(self):
        payload = self.table()
        region = next(r for r in payload["coverage"]["regions"] if r.get("layout"))
        region["layout"]["raw_headers"][1] = "EC50 (nM)"
        self.assertTrue(self.check(payload))

    def test_self_consistent_saved_context_cannot_replace_the_original_target(self):
        payload = self.table()
        region = next(r for r in payload["coverage"]["regions"] if r.get("layout"))
        context = region["layout"]["context"]
        for key, value in context.items():
            if isinstance(value, str):
                context[key] = value.replace("IRF5", "IRF4")
        for source in payload["rows"][0]["activity_sources"]:
            for key in set(source) & set(context):
                source[key] = context[key]
        self.assertTrue(self.check(payload))

    def test_malformed_native_context_column_is_a_source_failure_not_an_attribute_crash(
        self,
    ):
        payload = self.mixed_context()
        payload["header_observations"]["controlled-scope"]["original_source"][
            "columns"
        ][0] = None
        self.assertTrue(self.check(payload))
