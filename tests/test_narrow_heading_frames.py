"""Generated original frames: geometry nomination is not product acceptance."""

import hashlib
import json
import unittest
from unittest.mock import patch

import fitz

from patent_sar_extractor.core.caption_grid_binding import bind_caption_grids
from patent_sar_extractor.core.heading_cell_source import observe_cell_source
from patent_sar_extractor.core.heading_observation import observe_heading
from patent_sar_extractor.core.heading_original_replay import validate_original_heading
from patent_sar_extractor.core.heading_source_proof import proved_heading_declaration
from patent_sar_extractor.core.table_geometry import detect_ruled_table_regions


def draw_frame(page, box, *, missing=None, dotted=False):
    x0, y0, x1, y1 = box
    for name, start, end in (
        ("top", (x0, y0), (x1, y0)),
        ("bottom", (x0, y1), (x1, y1)),
        ("left", (x0, y0), (x0, y1)),
        ("right", (x1, y0), (x1, y1)),
    ):
        if name != missing:
            page.draw_line(
                start, end, width=0.4, dashes="[0.8 0.6] 0" if dotted else None
            )


class NarrowHeadingFrameTests(unittest.TestCase):
    def test_single_column_frame_does_not_depend_on_blank_page_width(self):
        for width, page_width in ((44, 360), (68, 360), (68, 1800), (94, 1800)):
            with self.subTest(width=width, page_width=page_width), fitz.open() as doc:
                page = doc.new_page(width=page_width, height=240)
                draw_frame(page, [40, 60, 40 + width, 90])
                self.assertEqual(detect_ruled_table_regions(page, dpi=240), [])
                grids = detect_ruled_table_regions(page, dpi=240, minimum_columns=1)
                self.assertEqual(len(grids), 1)
                self.assertEqual(len(grids[0]["xs"]), 2)
                for observed, expected in zip(
                    grids[0]["bbox"], (40, 60, 40 + width, 90)
                ):
                    self.assertAlmostEqual(observed, expected, delta=0.5)

    def test_narrow_frame_cannot_invent_a_missing_original_edge(self):
        for missing in ("top", "bottom", "left", "right"):
            with self.subTest(missing=missing), fitz.open() as doc:
                page = doc.new_page(width=360, height=240)
                draw_frame(page, [40, 60, 108, 90], missing=missing)
                self.assertEqual(
                    detect_ruled_table_regions(page, dpi=240, minimum_columns=1), []
                )

    def test_short_chemical_marks_are_not_promoted_into_a_full_height_frame(self):
        with fitz.open() as doc:
            page = doc.new_page(width=360, height=240)
            draw_frame(page, [40, 60, 108, 68])
            self.assertEqual(
                detect_ruled_table_regions(page, dpi=240, minimum_columns=1), []
            )

    def test_adjacent_narrow_frames_keep_separate_original_sources(self):
        with fitz.open() as doc:
            page = doc.new_page(width=360, height=240)
            for left in (40, 118):
                draw_frame(page, [left, 60, left + 68, 90])
            grids = detect_ruled_table_regions(page, dpi=240, minimum_columns=1)
            self.assertEqual(len(grids), 2)
            self.assertLess(grids[0]["bbox"][2], grids[1]["bbox"][0])

    def test_dotted_narrow_frame_uses_the_existing_closed_cell_witness(self):
        with fitz.open() as doc:
            page = doc.new_page(width=360, height=240)
            draw_frame(page, [40, 60, 108, 90], dotted=True)
            page.insert_text((46, 80), "Compound 72", fontsize=7.5)
            grids = detect_ruled_table_regions(page, dpi=240, minimum_columns=1)
            source = observe_cell_source(page, [46, 70, 99, 83], grids, 128)
            self.assertIsNotNone(source)
            self.assertEqual(source["version"], 1)
            self.assertEqual(len(source["pixels"]["readings"]), 2)

    def test_extra_margin_ink_still_refuses_the_closed_cell_witness(self):
        with fitz.open() as doc:
            page = doc.new_page(width=360, height=240)
            draw_frame(page, [40, 60, 108, 90])
            page.insert_text((46, 80), "Compound 72", fontsize=7.5)
            page.draw_rect(fitz.Rect(40.8, 72, 41.2, 73), fill=(0, 0, 0), width=0)
            grids = detect_ruled_table_regions(page, dpi=240, minimum_columns=1)
            self.assertTrue(grids)
            self.assertIsNone(observe_cell_source(page, [46, 70, 99, 83], grids, 128))

    def test_narrow_numbered_catalog_uses_the_same_original_caption_binder(self):
        with fitz.open() as doc:
            page = doc.new_page(width=360, height=240)
            page.insert_text((40, 45), "Table 23. Compounds", fontsize=9)
            draw_frame(page, [40, 60, 108, 145])
            page.draw_line((40, 90), (108, 90), width=0.4)
            page.insert_text((46, 80), "Compound 72", fontsize=7.5)
            box = [52, 98, 98, 137]
            structures = {1: [{"id": "generated-drawing", "page_no": 1}]}
            with patch(
                "patent_sar_extractor.core.table_geometry.get_ocr_engine",
                side_effect=AssertionError("Native generated source needs no OCR"),
            ):
                result = bind_caption_grids(doc, structures, {1: [box]}, [1])
            self.assertEqual([item["label"] for item in result.bindings], ["72"])
            self.assertEqual(result.issues, [])
            self.assertEqual(result.bindings[0]["ownership"]["direction"], "above")

    def test_a_small_diagram_frame_is_not_a_numbered_product_catalog(self):
        with fitz.open() as doc:
            page = doc.new_page(width=360, height=240)
            draw_frame(page, [40, 60, 108, 90])
            page.insert_text((48, 80), "N", fontsize=9)
            structures = {1: [{"id": "generated-ring", "page_no": 1}]}
            result = bind_caption_grids(doc, structures, {1: [[42, 62, 106, 88]]}, [1])
            self.assertEqual(result.bindings, [])
            self.assertEqual(result.issues, [])
            self.assertEqual(result.pages, set())


class NarrowHeadingConsumerTests(unittest.TestCase):
    def observe(self, *, label="Compound 72", shadow=None):
        with fitz.open() as drawing:
            page = drawing.new_page(width=360, height=240)
            page.insert_text((46, 80), label, fontsize=7.5)
            words = page.get_text("words")
            box = [
                min(w[0] for w in words),
                min(w[1] for w in words),
                max(w[2] for w in words),
                max(w[3] for w in words),
            ]
            draw_frame(page, [40, 69, 116, 84])
            pixels = page.get_pixmap(matrix=fitz.Matrix(3, 3), alpha=False).tobytes(
                "png"
            )
        document = fitz.open()
        self.addCleanup(document.close)
        page = document.new_page(width=360, height=240)
        page.insert_image(page.rect, stream=pixels)
        page.insert_text((40, 220), "Generated source footer", fontsize=8)
        if shadow:
            page.insert_text((46, 80), shadow, fontsize=7.5, render_mode=3)
        nomination = {
            "text": "Compound 999",
            "source": "page_ocr",
            "bbox": box,
            "geometry_space": "rendered",
        }

        engine_calls = []

        def engine(image, *, use_det, use_cls):
            self.assertFalse(use_cls)
            engine_calls.append(use_det)
            if use_det:
                h, w = image.shape[:2]
                return [[[[0, 0], [w, 0], [w, h], [0, h]], label, 0.99]], None
            return [[label, 0.99]], None

        digest = hashlib.sha256(document.tobytes(no_new_id=True)).hexdigest()
        with (
            patch(
                "patent_sar_extractor.core.heading_observation.get_ocr_engine",
                return_value=("rapidocr", engine),
            ) as acquire,
            patch(
                "patent_sar_extractor.core.text_ocr.source_capture.refine_source_text",
                side_effect=lambda _page, _bounds, rows, **_kwargs: rows,
            ) as auxiliary,
        ):
            proof = observe_heading(page, nomination, digest)
        return document, proof, acquire.call_count, auxiliary.call_count, engine_calls

    def test_same_heading_chain_reads_the_full_frame_before_original_replay(self):
        document, proof, calls, auxiliary, engine_calls = self.observe()
        self.assertEqual(proof["version"], 2)
        self.assertEqual(calls, 1)
        self.assertEqual(auxiliary, 0)
        self.assertEqual(engine_calls, [False, False])
        self.assertEqual(proof["original_heading"]["observations"], [])
        saved = json.loads(json.dumps(proof))
        self.assertEqual(proved_heading_declaration(saved)["identifier"], "72")
        self.assertEqual(saved["nomination"]["text"], "Compound 999")
        validate_original_heading(document[0], saved)
        document[0].draw_rect(fitz.Rect(102, 74, 104, 76), fill=(0, 0, 0), width=0)
        with self.assertRaises(ValueError):
            validate_original_heading(document[0], saved)

    def test_closed_frame_does_not_prove_an_unknown_or_negative_role(self):
        _, proof, _, _, _ = self.observe(label="Not Compound 72")
        self.assertIsNone(proved_heading_declaration(proof))

    def test_native_identifier_conflict_is_not_outvoted_by_the_frame(self):
        _, proof, _, _, _ = self.observe(shadow="Compound 73")
        self.assertIsNone(proved_heading_declaration(proof))


if __name__ == "__main__":
    unittest.main()
