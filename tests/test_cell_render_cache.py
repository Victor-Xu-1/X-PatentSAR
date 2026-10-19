"""Original cell pixels must not depend on prior PDF decoder tile caching."""

import hashlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from patent_sar_extractor.core.cell_frame_proof import original_cell_frame_matches
from patent_sar_extractor.core.cell_rendering import isolated_original_page
from patent_sar_extractor.core.table_cells import (
    CellRenderLimit,
    cell_image,
    observe_original_cell,
)


def scanned_source(mode="1"):
    image = Image.new("RGB", (2479, 3507), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=40)
    for index in range(20):
        y = 127 + index * 150
        draw.text((300, y), f"Compound {index + 17}B", font=font, fill="black")
        draw.line((100, y + 80, 2300, y + 80), fill="black", width=3)
    stream = io.BytesIO()
    image.convert(mode).save(stream, format="PDF", resolution=300)
    with fitz.open(stream=stream.getvalue(), filetype="pdf") as document:
        document[0].set_mediabox(fitz.Rect(0, 0, 595, 842))
        return document.tobytes()


class CellRenderCacheTests(unittest.TestCase):
    def test_one_bit_scan_cells_survive_prior_full_page_render(self):
        source = scanned_source()
        # Deliberately noninteger source transform and cell origin. This is an
        # authored CCITT source, not a private patent page or a recognition run.
        with fitz.open(stream=source, filetype="pdf") as original:
            self.assertEqual(original[0].get_images()[0][4], 1)
        for dpi in (400, 600):
            frames = []
            for warm in (False, True):
                with fitz.open(stream=source, filetype="pdf") as document:
                    if warm:
                        document[0].get_pixmap(
                            matrix=fitz.Matrix(200 / 72, 200 / 72), alpha=False
                        )
                    frames.append(
                        cell_image(document[0], [70.35, 460.35, 216.75, 475.05], dpi)
                    )
            with self.subTest(dpi=dpi):
                np.testing.assert_array_equal(frames[0], frames[1])

    def test_gray_and_rgb_source_bytes_keep_exact_clipped_pixels(self):
        for mode in ("L", "RGB"):
            with fitz.open(stream=scanned_source(mode), filetype="pdf") as document:
                bounds = [70.35, 460.35, 216.75, 475.05]
                clip = fitz.Rect(71.85, 461.55, 215.25, 473.85)
                expected = document[0].get_pixmap(
                    matrix=fitz.Matrix(400 / 72, 400 / 72), clip=clip, alpha=False
                )
                with self.subTest(mode=mode):
                    np.testing.assert_array_equal(
                        cell_image(document[0], bounds, 400),
                        np.frombuffer(expected.samples, np.uint8).reshape(
                            expected.height, expected.width, 3
                        ),
                    )

    def test_unchanged_file_is_lazy_not_serialized_or_modified(self):
        source = scanned_source()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Original source with spaces.pdf"
            path.write_bytes(source)
            with fitz.open(path) as document:
                with patch.object(
                    document, "tobytes", side_effect=AssertionError("No full copy")
                ):
                    cold = cell_image(document[0], [70.35, 460.35, 216.75, 475.05], 400)
                    document[0].get_pixmap(matrix=fitz.Matrix(3, 3), alpha=False)
                    warm = cell_image(document[0], [70.35, 460.35, 216.75, 475.05], 400)
                np.testing.assert_array_equal(cold, warm)
            self.assertEqual(path.read_bytes(), source)

    def test_current_memory_edits_are_not_replaced_by_saved_file(self):
        with tempfile.TemporaryDirectory() as directory, fitz.open() as created:
            page = created.new_page(width=300, height=200)
            page.insert_text((30, 50), "Original 14A")
            path = Path(directory) / "saved.pdf"
            created.save(path)
            before = path.read_bytes()
            with fitz.open(path) as document:
                document[0].insert_text((30, 90), "Current source 26B")
                expected = document[0].get_pixmap(
                    matrix=fitz.Matrix(2, 2),
                    clip=fitz.Rect(21.5, 66.2, 198.5, 108.8),
                    alpha=False,
                )
                np.testing.assert_array_equal(
                    cell_image(document[0], [20, 65, 200, 110], 144),
                    np.frombuffer(expected.samples, np.uint8).reshape(
                        expected.height, expected.width, 3
                    ),
                )
            self.assertEqual(path.read_bytes(), before)

    def test_original_visibility_annotations_widgets_crop_and_rotation_survive(self):
        for rotation in (0, 90, 180, 270):
            with fitz.open() as created:
                page = created.new_page(width=500, height=700)
                page.insert_text((70, 100), "Original 27B", fontsize=20)
                shown = created.add_ocg("visible", on=True)
                hidden = created.add_ocg("hidden", on=False)
                page.insert_text((70, 140), "Shown", oc=shown)
                page.insert_text((70, 180), "Must remain hidden", oc=hidden)
                created.set_layer(-1, on=[shown], off=[hidden], basestate="OFF")
                page.add_freetext_annot(fitz.Rect(70, 220, 180, 250), "Note 55C")
                widget = fitz.Widget()
                widget.field_name = "literal"
                widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
                widget.field_value = "77A"
                widget.rect = fitz.Rect(70, 270, 180, 300)
                page.add_widget(widget)
                page.set_cropbox(fitz.Rect(35, 48, 440, 610))
                page.set_rotation(rotation)
                data = created.tobytes()
            with fitz.open(stream=data, filetype="pdf") as document:
                page = document[0]
                bounds = [0, 0, page.rect.width, page.rect.height]
                expected = page.get_pixmap(
                    matrix=fitz.Matrix(2, 2),
                    clip=fitz.Rect(1.5, 1.2, bounds[2] - 1.5, bounds[3] - 1.2),
                    alpha=False,
                )
                with self.subTest(rotation=rotation):
                    self.assertFalse(document.get_ocgs()[hidden]["on"])
                    np.testing.assert_array_equal(
                        cell_image(page, bounds, 144),
                        np.frombuffer(expected.samples, np.uint8).reshape(
                            expected.height, expected.width, 3
                        ),
                    )

    def test_original_frame_replays_after_full_page_and_rejects_changed_pixels(self):
        source = scanned_source()
        bounds = [70.35, 460.35, 216.75, 475.05]
        with fitz.open(stream=source, filetype="pdf") as document:
            # Controlled reader only supplies a carrier; actual source pixels,
            # ink geometry and replay below use the real PDF implementation.
            def reader(image, **kwargs):
                return [["17", 0.99]], None

            reading = observe_original_cell(
                document[0], bounds, "number", 400, reader, lambda value, kind: value
            ).evidence(400, bounds)
            self.assertEqual(reading["text"], "17")
            document[0].get_pixmap(matrix=fitz.Matrix(3, 3), alpha=False)
            self.assertTrue(original_cell_frame_matches(reading, document[0]))
            reading["source_frame"]["pixel_sha256"] = hashlib.sha256(
                b"wrong"
            ).hexdigest()
            self.assertFalse(original_cell_frame_matches(reading, document[0]))

    def test_fresh_document_closes_on_normal_and_exceptional_exit(self):
        with fitz.open(stream=scanned_source(), filetype="pdf") as document:
            with isolated_original_page(document[0]) as page:
                normal = page.parent
                self.assertFalse(normal.is_closed)
            self.assertTrue(normal.is_closed)
            with (
                self.assertRaisesRegex(RuntimeError, "controlled interruption"),
                isolated_original_page(document[0]) as page,
            ):
                interrupted = page.parent
                raise RuntimeError("controlled interruption")
            self.assertTrue(interrupted.is_closed)
            self.assertFalse(document.is_closed)

    def test_limit_refuses_before_open_and_reopen_fault_has_no_old_pixel_fallback(self):
        with fitz.open(stream=scanned_source(), filetype="pdf") as document:
            with (
                patch(
                    "patent_sar_extractor.core.table_cells.original_cell_pixmap",
                    side_effect=AssertionError("Budget must refuse first"),
                ),
                self.assertRaises(CellRenderLimit),
            ):
                cell_image(document[0], [10, 10, 200, 200], 400, maximum_pixels=10)
            with (
                patch(
                    "fitz.open", side_effect=OSError("Controlled source unavailable")
                ),
                self.assertRaisesRegex(OSError, "source unavailable"),
            ):
                cell_image(document[0], [70.35, 460.35, 216.75, 475.05], 400)

    def test_no_process_global_cache_eviction_is_needed(self):
        with (
            fitz.open(stream=scanned_source(), filetype="pdf") as document,
            patch.object(
                fitz.TOOLS, "store_shrink", side_effect=AssertionError("No global trim")
            ),
        ):
            self.assertTrue(
                cell_image(document[0], [70.35, 460.35, 216.75, 475.05], 400).size
            )

    def test_changed_source_context_refuses_and_closes_its_decoder(self):
        data = scanned_source()
        with fitz.open(stream=data, filetype="pdf") as source:
            replacement = fitz.open(stream=data, filetype="pdf")
            replacement[0].set_rotation(90)
            with (
                patch("fitz.open", return_value=replacement),
                self.assertRaisesRegex(ValueError, "page context differs"),
                isolated_original_page(source[0]),
            ):
                self.fail("Changed context must not render")
            self.assertTrue(replacement.is_closed)
            self.assertFalse(source.is_closed)

    def test_authenticated_original_remains_private_and_renderable(self):
        with fitz.open() as created:
            page = created.new_page(width=300, height=200)
            page.insert_text((30, 50), "Original 14A")
            encrypted = created.tobytes(
                encryption=fitz.PDF_ENCRYPT_AES_256,
                owner_pw="controlled-owner",
                user_pw="controlled-reader",
            )
        with fitz.open(stream=encrypted, filetype="pdf") as source:
            self.assertTrue(source.needs_pass)
            self.assertTrue(source.authenticate("controlled-reader"))
            image = cell_image(source[0], [20, 20, 190, 70], 144)
            self.assertTrue(np.any(image < 180))
            self.assertTrue(source.needs_pass)


if __name__ == "__main__":
    unittest.main()
