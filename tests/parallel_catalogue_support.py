"""Generated original source controls; never invokes native OCR factories."""

from unittest.mock import patch

import fitz

from patent_sar_extractor.core.caption_role_observation import observe_caption_role
from patent_sar_extractor.core.source_geometry import SourceTokens, source_layout
from patent_sar_extractor.core.table_geometry import detect_ruled_table_regions

TITLES = ("Table A. Compounds", "Table B. Intermediates")


def original_parallel_catalogues(
    mode="native",
    *,
    titles=TITLES,
    extra_title=None,
    right_shift=0,
    open_right=False,
    headers=False,
):
    document = fitz.open()
    page = document.new_page(width=740, height=300)
    frames, structures, boxes = [], [], []
    for column, offset in enumerate((30, 400)):
        shift = right_shift if column else 0
        xs, ys = (
            [offset, offset + 120, offset + 240],
            [100 + shift, 125 + shift, 205 + shift],
        )
        frames.append({"xs": xs, "ys": ys})
        for x in xs:
            if open_right and column == 1 and x == xs[-1]:
                continue
            page.draw_line((x, ys[0]), (x, ys[-1]))
        for y in ys:
            page.draw_line((xs[0], y), (xs[-1], y))
        if headers:
            page.insert_text((xs[0] + 15, 117 + shift), "No.", fontsize=8)
            page.insert_text((xs[1] + 15, 117 + shift), "Structure", fontsize=8)
        for member in range(1 if headers else 2):
            left = xs[member] + 15
            label = f"{column + 1}{member + 1}A"
            page.insert_text(
                (left, (165 if headers else 117) + shift),
                "Compound " + label,
                fontsize=8,
            )
            drawing_left = xs[1] + 15 if headers else left
            box = [drawing_left + 5, 145 + shift, drawing_left + 65, 177 + shift]
            page.draw_line((box[0], box[1] + 10), (box[0] + 30, box[1]))
            page.draw_line((box[0] + 30, box[1]), (box[2], box[1] + 10))
            structures.append(
                {
                    "id": f"original-{column}-{member}",
                    "page_no": 1,
                    **dict(zip(("x0", "y0", "x1", "y1"), box)),
                }
            )
            boxes.append(tuple(box))
    if mode == "native":
        for x, title in zip((30, 400), titles, strict=True):
            page.insert_text((x, 85), title, fontsize=9)
    else:
        with fitz.open() as lettering:
            heading = lettering.new_page(width=740, height=96)
            for x, title in zip((30, 400), titles, strict=True):
                heading.insert_text((x, 85), title, fontsize=9)
            if extra_title is not None:
                heading.insert_text((290, 85), extra_title, fontsize=7)
            if mode == "raster":
                image = heading.get_pixmap(matrix=fitz.Matrix(3, 3), alpha=False)
                page.insert_image(fitz.Rect(0, 0, 740, 96), stream=image.tobytes("png"))
            else:
                with (
                    fitz.open(
                        stream=heading.get_svg_image(text_as_path=True).encode(),
                        filetype="svg",
                    ) as vector,
                    fitz.open(stream=vector.convert_to_pdf(), filetype="pdf") as pdf,
                ):
                    page.show_pdf_page(fitz.Rect(0, 0, 740, 96), pdf, 0)
    return document, {1: structures}, {1: boxes}, frames


def title_reader(literal, confidence=0.99):
    def read(image, *, use_det, use_cls):
        return ([], None) if use_det else ([[literal, confidence]], None)

    return read


class ParallelCatalogueControls:
    def setUp(self):
        self.factory = self.enterContext(
            patch(
                "patent_sar_extractor.core.page_ocr_cache._build_ocr_engine",
                side_effect=AssertionError("No native OCR in controlled source cases"),
            )
        )
        self.enterContext(
            patch(
                "patent_sar_extractor.core.text_ocr.source_capture.get_auxiliary_text_runtime",
                return_value=None,
            )
        )

    def tearDown(self):
        self.assertEqual(self.factory.call_count, 0)

    def scopes(self, document, frames, *, title_cache=None):
        page = document[0]
        layout = source_layout(page)
        tokens = SourceTokens(layout.native, layout, layout.raster_bounds)
        if len(frames) == 2:
            self.assertGreaterEqual(len(detect_ruled_table_regions(page, dpi=240)), 1)
        return [
            observe_caption_role(page, frame, frames, tokens, title_cache=title_cache)
            for frame in frames
        ]

    def readers(self, titles=TITLES):
        from itertools import cycle

        values = cycle(titles)
        return lambda: ("rapidocr", title_reader(next(values)))
