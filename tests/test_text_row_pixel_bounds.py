"""Source rows use an integer raster extent, not a fractional pixel rejection."""

import io
import math
import unittest

import fitz
import numpy as np
from PIL import Image

from patent_sar_extractor.core.caption_word_geometry import caption_word_partitions
from patent_sar_extractor.core.cell_header_lines import physical_line_frame
from patent_sar_extractor.core.cell_line_coverage import complete_line_bounds
from patent_sar_extractor.core.cell_text_chunks import observe_text_cell
from patent_sar_extractor.core.cell_text_limits import row_pixel_limit
from patent_sar_extractor.core.cell_text_proof import valid_text_reading


def original_rows(height, count=2):
    image = np.full((count * (height + 14) + 12, 260, 3), 255, dtype=np.uint8)
    for row in range(count):
        top = 6 + row * (height + 14)
        image[top : top + height, 12:80] = 0
        image[top : top + height, 105:245] = 0
    return image


def controlled_reader(image, *, use_det, use_cls):
    if use_det:
        return [[[[0, 0], [20, 0], [20, 20], [0, 20]], "Original rows", 0.99]], None
    return [["Original row", 0.99]], None


def printed_rows(height):
    """Create a synthetic source; no production input resizing is requested."""
    pieces = []
    with fitz.open() as document:
        for text in ("NMR (500 MHz)", "MS (ESI) m/z 287.2"):
            page = document.new_page(width=480, height=70)
            page.insert_text((10, 45), text, fontsize=20, fontname="hebo")
            pixmap = page.get_pixmap(matrix=fitz.Matrix(3, 3), alpha=False)
            original = np.frombuffer(pixmap.samples, np.uint8).reshape(
                pixmap.height, pixmap.width, 3
            )
            yy, xx = np.where(original.min(axis=2) < 180)
            ink = original[yy.min() : yy.max() + 1, xx.min() : xx.max() + 1]
            width = round(ink.shape[1] * height / ink.shape[0])
            pieces.append(
                np.asarray(
                    Image.fromarray(ink).resize(
                        (width, height), Image.Resampling.NEAREST
                    )
                )
            )
    image = np.full(
        (2 * height + 42, max(p.shape[1] for p in pieces) + 24, 3), 255, np.uint8
    )
    for index, piece in enumerate(pieces):
        top = 10 + index * (height + 14)
        image[top : top + height, 12 : 12 + piece.shape[1]] = piece
    return image


class TextRowPixelBoundsTests(unittest.TestCase):
    def test_actual_characterization_capture_and_saved_reference_keep_primary_id(self):
        from test_activity_spatial_roles import ruled

        from patent_sar_extractor.core.binding_source_references import (
            reference_issues,
            reference_scope,
        )
        from patent_sar_extractor.core.binding_source_regions import (
            identifier_references,
            reference_regions,
        )
        from patent_sar_extractor.core.table_geometry import page_tokens

        image = printed_rows(67)
        encoded = io.BytesIO()
        Image.fromarray(image).save(encoded, format="PNG")
        with fitz.open() as original, fitz.open() as scanned:
            page = original.new_page(width=576, height=432)
            page.insert_text(
                (40, 65), "Table 19. Compound characterization", fontsize=10
            )
            ruled(
                page,
                [40, 140, 320, 550],
                [80, 110, 178],
                [
                    ["Compound No.", "Preparation", "Characterization"],
                    ["Compound 73", "Prepared in analogy to\nCompound 91", ""],
                ],
            )
            page.insert_image(
                fitz.Rect(
                    331.2,
                    120.6,
                    331.2 + image.shape[1] * 0.18,
                    120.6 + image.shape[0] * 0.18,
                ),
                stream=encoded.getvalue(),
            )
            pixmap = page.get_pixmap(
                matrix=fitz.Matrix(400 / 72, 400 / 72), alpha=False
            )
            target = scanned.new_page(width=576, height=432)
            target.insert_image(target.rect, stream=pixmap.tobytes("png"))
            tokens = page_tokens(target, dpi=200, allow_tesseract=False)
            regions = reference_regions(
                target, original_pdf_sha256="a" * 64, tokens=tokens
            )
        self.assertEqual(len(regions), 1)
        self.assertEqual(
            regions[0]["role_scope"]["roles"]["columns"],
            ["identifier", "preparation", "characterization"],
        )
        references = identifier_references(regions[0])
        self.assertEqual([ref["identifier"] for ref in references], ["73"])
        sections = [
            {
                "role": "characterization_region",
                "page_no": 1,
                "source_region": regions[0],
            },
            *references,
        ]
        payload = {
            "source_sections": sections,
            "source_reference_scope": reference_scope(sections),
        }
        self.assertEqual(reference_issues(payload, [{"cpd": "Compound 73"}]), [])
        self.assertEqual(
            [issue["cpd"] for issue in reference_issues(payload, [])], ["Compound 73"]
        )

    def test_exact_point_rows_survive_native_render_origin_phases(self):
        for dpi, points in ((400, 12), (600, 12), (400, 128), (600, 128)):
            for phase in (0, 0.2, 0.4, 0.6, 0.8):
                with (
                    self.subTest(dpi=dpi, points=points, phase=phase),
                    fitz.open() as document,
                ):
                    page = document.new_page(width=90, height=2 * points + 56)
                    shift = phase * 72 / dpi
                    for top in (10 + shift, points + 26 + shift):
                        page.draw_rect(
                            fitz.Rect(12, top, 70, top + points),
                            color=None,
                            fill=(0, 0, 0),
                            width=0,
                        )
                    pixmap = page.get_pixmap(
                        matrix=fitz.Matrix(dpi / 72, dpi / 72), alpha=False
                    )
                    source = np.frombuffer(pixmap.samples, np.uint8).reshape(
                        pixmap.height, pixmap.width, 3
                    )
                    frame = physical_line_frame(
                        source, 0, dpi, maximum_row_height=points
                    )
                    self.assertEqual(len(frame["row_bounds"]), 2)

    def test_one_integer_extent_authority_rejects_invalid_parameters(self):
        for dpi, points in (
            (True, 12),
            (399, 12),
            (400, True),
            (400, 0),
            (600, 129),
            (400, 12.0),
        ):
            with self.subTest(dpi=dpi, points=points), self.assertRaises(ValueError):
                row_pixel_limit(dpi, maximum_row_height=points)
        self.assertEqual(row_pixel_limit(400), 68)
        self.assertEqual(row_pixel_limit(600), 101)

    def test_complete_physical_rows_include_fractional_pixel_cover(self):
        for dpi, points in ((400, 12), (600, 12), (400, 128), (600, 128)):
            height = math.ceil(points * dpi / 72)
            with self.subTest(dpi=dpi, points=points):
                source = original_rows(height)
                frame = physical_line_frame(source, 0, dpi, maximum_row_height=points)
                self.assertEqual(len(frame["row_bounds"]), 2)
                self.assertEqual(
                    [b[3] - b[1] for b in frame["row_bounds"]], [height] * 2
                )

    def test_a_pixel_beyond_the_integer_bound_still_refuses(self):
        for dpi, points in ((400, 12), (600, 12), (400, 128), (600, 128)):
            with self.subTest(dpi=dpi, points=points):
                height = row_pixel_limit(dpi, maximum_row_height=points) + 1
                frame = physical_line_frame(
                    original_rows(height), 0, dpi, maximum_row_height=points
                )
                self.assertEqual(frame["row_bounds"], [])

    def test_over_bound_text_never_requests_extra_model_reads(self):
        calls = []

        def reader(*args, **kwargs):
            calls.append(args)
            raise AssertionError("Over-bound original must not request a repair read")

        source = original_rows(row_pixel_limit(400) + 1)
        observed = observe_text_cell(source, 400, reader)
        self.assertEqual(observed.value, "")
        self.assertEqual(calls, [])

    def test_boundary_geometry_does_not_qualify_weak_or_malformed_confidence(self):
        for score in (0.84, None, True, "0.99"):
            with self.subTest(score=score):

                def reader(image, *, use_det, use_cls, confidence=score):
                    if use_det:
                        return [], None
                    return [["Original row", confidence]], None

                reading = observe_text_cell(original_rows(67), 400, reader).evidence(
                    400, [0, 0, 50, 50]
                )
                self.assertEqual(reading["text"], "")
                self.assertFalse(
                    valid_text_reading(
                        reading, [0, 0, 50, 50], 400, maximum_rows=32, allow_chunks=True
                    )
                )

    def test_normal_long_text_carrier_and_saved_proof_share_the_limit(self):
        for dpi in (400, 600):
            with self.subTest(dpi=dpi):
                source = original_rows(math.ceil(12 * dpi / 72))
                reading = observe_text_cell(source, dpi, controlled_reader).evidence(
                    dpi, [0, 0, 50, 50]
                )
                self.assertEqual(reading["text"], "Original row\nOriginal row")
                self.assertTrue(
                    valid_text_reading(
                        reading, [0, 0, 50, 50], dpi, maximum_rows=32, allow_chunks=True
                    )
                )

    def test_chunked_original_text_preserves_every_boundary_height_row(self):
        source = original_rows(67, 3)
        reading = observe_text_cell(
            source, 400, controlled_reader, rows_per_chunk=2
        ).evidence(400, [0, 0, 50, 50])
        self.assertEqual(reading["text"], "\n".join(["Original row"] * 3))
        self.assertEqual(len(reading["physical_text_chunks"]["chunks"]), 2)
        self.assertTrue(
            valid_text_reading(
                reading, [0, 0, 50, 50], 400, maximum_rows=2, allow_chunks=True
            )
        )

    def test_single_row_compact_read_and_saved_proof_share_the_limit(self):
        calls = []

        def reader(image, *, use_det, use_cls):
            self.assertFalse(use_det)
            calls.append(image.shape)
            return [["Original row", 0.4 if len(calls) == 1 else 0.99]], None

        reading = observe_text_cell(original_rows(67, 1), 400, reader).evidence(
            400, [0, 0, 50, 50]
        )
        self.assertEqual(len(calls), 2)
        self.assertEqual(reading["text"], "Original row")
        self.assertTrue(
            valid_text_reading(
                reading, [0, 0, 50, 50], 400, maximum_rows=32, allow_chunks=True
            )
        )

    def test_real_existing_ocr_reads_complete_boundary_height_analytical_rows(self):
        from patent_sar_extractor.core.page_ocr_cache import get_ocr_engine

        backend = get_ocr_engine()
        self.assertIsNotNone(backend)
        self.assertEqual(backend[0], "rapidocr")
        for dpi in (400, 600):
            with self.subTest(dpi=dpi):
                source = printed_rows(row_pixel_limit(dpi))
                reading = observe_text_cell(source, dpi, backend[1]).evidence(
                    dpi, [0, 0, 50, 50]
                )
                self.assertIn("NMR", reading["text"])
                self.assertIn("287.2", reading["text"])
                self.assertEqual(len(reading["parts"]), 2)
                self.assertTrue(
                    valid_text_reading(
                        reading, [0, 0, 50, 50], dpi, maximum_rows=32, allow_chunks=True
                    )
                )

    def test_caption_and_word_source_share_the_same_integer_bound(self):
        for dpi in (400, 600):
            height = math.ceil(12 * dpi / 72)
            with self.subTest(dpi=dpi):
                source = original_rows(height, 1)
                self.assertIsNotNone(complete_line_bounds(source, [], 8, dpi))
                self.assertIsNotNone(
                    caption_word_partitions(source.min(axis=2) < 180, dpi)
                )
                oversized = original_rows(row_pixel_limit(dpi) + 1, 1)
                self.assertIsNone(complete_line_bounds(oversized, [], 8, dpi))
                self.assertIsNone(
                    caption_word_partitions(oversized.min(axis=2) < 180, dpi)
                )


if __name__ == "__main__":
    unittest.main()
