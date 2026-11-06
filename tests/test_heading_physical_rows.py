"""Generated original raster headings must not borrow adjacent clipped ink."""

import copy
import hashlib
import json
import unittest
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import fitz
import numpy as np

from patent_sar_extractor.core.binding_source_headings import (
    observed_heading_blocks,
    select_heading_bindings,
)
from patent_sar_extractor.core.heading_observation import observe_heading
from patent_sar_extractor.core.heading_original_replay import validate_original_heading
from patent_sar_extractor.core.heading_source_proof import proved_heading_declaration


@contextmanager
def raster_heading(
    literal="Example 17: Synthesis of Compound 29",
    *,
    neighbors=True,
    following="Next independent experimental paragraph.",
    following_y=104,
):
    """A real generated PDF raster, with a tightly located printed title row."""
    with fitz.open() as source:
        page = source.new_page(width=500, height=260)
        if neighbors:
            page.insert_text(
                (40, 82), "Previous result, 3.24 (m, 2H), 1.27 (d, 3H).", fontsize=8
            )
            page.insert_text((40, following_y), following, fontsize=8)
        page.insert_text((40, 92), literal, fontsize=8, fontname="tibo")
        width = fitz.get_text_length(literal, fontname="tibo", fontsize=8)
        image = page.get_pixmap(matrix=fitz.Matrix(4, 4)).tobytes("png")
    with fitz.open() as document:
        page = document.new_page(width=500, height=260)
        page.insert_image(page.rect, stream=image)
        yield (
            document,
            page,
            {
                "text": literal,
                "bbox": [40, 85, 40 + width, 93],
                "source": "page_ocr",
                "geometry_space": "rendered",
            },
        )


def controlled_reader(literal):
    """Only text responses are controlled; all pixel/row ownership is original."""

    def read(image, *, use_det, use_cls):
        ys, xs = np.where(np.min(image, axis=2) < 180)
        if not len(xs):
            return [], None
        if use_det:
            return [
                [
                    [
                        [int(xs.min()), int(ys.min())],
                        [int(xs.max()) + 1, int(ys.min())],
                        [int(xs.max()) + 1, int(ys.max()) + 1],
                        [int(xs.min()), int(ys.max()) + 1],
                    ],
                    literal,
                    0.99,
                ]
            ], None
        if int(ys.max()) - int(ys.min()) < 12:
            return [[",,", 0.3]], None
        return [[literal, 0.99]], None

    return read


class HeadingPhysicalRowTests(unittest.TestCase):
    def observe(self, page, nomination, literal=None):
        digest = hashlib.sha256(page.parent.tobytes(no_new_id=True)).hexdigest()
        with (
            patch(
                "patent_sar_extractor.core.heading_observation.get_ocr_engine",
                return_value=(
                    "rapidocr",
                    controlled_reader(literal or nomination["text"]),
                ),
            ),
            patch(
                "patent_sar_extractor.core.text_ocr.source_capture.get_auxiliary_text_runtime",
                return_value=None,
            ),
        ):
            return observe_heading(page, nomination, digest, grids=[])

    def test_adjacent_clipped_text_does_not_poison_a_complete_raster_title(self):
        with raster_heading() as (_, page, nomination):
            proof = json.loads(json.dumps(self.observe(page, nomination)))
            self.assertIsNotNone(proved_heading_declaration(proof))
            self.assertEqual(proof["title_scope"]["method"], "raster_row")
            self.assertGreater(proof["bbox"][1], 80)
            self.assertLess(proof["bbox"][3], 100)
            self.assertTrue(
                all(r["raw_text"] == nomination["text"] for r in proof["observations"])
            )
            validate_original_heading(page, proof)

    def test_partial_word_locator_cannot_drop_a_same_row_nonfinal_prefix(self):
        literal = "Intermediate Compound 41"
        with raster_heading(literal) as (_, page, nomination):
            nomination["text"] = "Compound 41"
            nomination["bbox"][0] = 40 + fitz.get_text_length(
                "Intermediate ", fontsize=8, fontname="tibo"
            )
            proof = self.observe(page, nomination, literal)
            self.assertLess(proof["bbox"][0], nomination["bbox"][0] - 20)
            self.assertEqual(
                proved_heading_declaration(proof)["role"], "intermediate_section"
            )
            validate_original_heading(page, proof)

    def test_original_context_changes_outside_the_selected_title_invalidate_replay(
        self,
    ):
        with raster_heading() as (_, page, nomination):
            proof = self.observe(page, nomination)
            self.assertIsNotNone(proved_heading_declaration(proof))
            page.draw_rect(fitz.Rect(45, 76, 47, 78), fill=(0, 0, 0), color=None)
            with self.assertRaises(ValueError):
                validate_original_heading(page, proof)

    def test_removed_or_forged_source_rows_cannot_retain_the_success_flag(self):
        with raster_heading() as (_, page, nomination):
            proof = self.observe(page, nomination)
            self.assertIsNotNone(proved_heading_declaration(proof))
            for field in ("pixels", "nomination_bbox", "page_size"):
                changed = copy.deepcopy(proof)
                changed["title_scope"][field] = None
                self.assertIsNone(proved_heading_declaration(changed), field)

    def test_unqualified_title_is_not_replaced_by_the_locator_text(self):
        with raster_heading() as (_, page, nomination):
            proof = self.observe(page, nomination, "Unreadable source")
            self.assertIsNone(proved_heading_declaration(proof))

    def test_disagreeing_complete_original_views_do_not_choose_a_number(self):
        with raster_heading("Compound 029B") as (_, page, nomination):
            labels = iter(("Compound 029B", "Compound 031B"))

            def reader(image, *, use_det, use_cls):
                return ([], None) if use_det else ([[next(labels), 0.99]], None)

            digest = hashlib.sha256(page.parent.tobytes(no_new_id=True)).hexdigest()
            with (
                patch(
                    "patent_sar_extractor.core.heading_observation.get_ocr_engine",
                    return_value=("rapidocr", reader),
                ),
                patch(
                    "patent_sar_extractor.core.text_ocr.source_capture.get_auxiliary_text_runtime",
                    return_value=None,
                ),
            ):
                proof = observe_heading(page, nomination, digest, grids=[])
            self.assertIsNone(proved_heading_declaration(proof))

    def test_the_normal_binder_receives_the_qualified_printed_id_and_original_crop(
        self,
    ):
        with (
            TemporaryDirectory(prefix="heading-row-producer-") as folder,
            raster_heading(
                "Compound 029B", following="Step 1: Preparation", following_y=235
            ) as (doc, page, nomination),
        ):
            polygon = [
                (140, 145),
                (180, 125),
                (220, 145),
                (220, 185),
                (180, 205),
                (140, 185),
                (140, 145),
            ]
            page.draw_polyline(polygon, width=1.5)
            bounds = [125, 115, 240, 215]
            image = Path(folder) / "structure.png"
            page.get_pixmap(matrix=fitz.Matrix(2, 2), clip=fitz.Rect(bounds)).save(
                image
            )
            structure = dict(
                zip(("x0", "y0", "x1", "y1"), bounds),
                id="S1",
                idx=1,
                page_no=1,
                image_path=str(image),
            )
            lines = {
                0: [
                    {
                        **nomination,
                        "y0": nomination["bbox"][1],
                        "y1": nomination["bbox"][3],
                    },
                    {
                        "text": "Step 1: Preparation",
                        "bbox": [40, 228, 150, 237],
                        "y0": 228,
                        "y1": 237,
                        "source": "page_ocr",
                        "geometry_space": "rendered",
                    },
                ]
            }
            original = Path(folder) / "original.pdf"
            doc.save(original)
            with (
                fitz.open(original) as captured,
                patch(
                    "patent_sar_extractor.core.heading_observation.get_ocr_engine",
                    return_value=("rapidocr", controlled_reader(nomination["text"])),
                ),
                patch(
                    "patent_sar_extractor.core.text_ocr.source_capture.get_auxiliary_text_runtime",
                    return_value=None,
                ),
            ):
                blocks = observed_heading_blocks(
                    captured, [0], {}, source_line_map=lines, source_regions={0: []}
                )
                self.assertTrue(blocks)
                found = blocks[0]["heading_observation"]
                self.assertIsNotNone(
                    proved_heading_declaration(found),
                    {
                        "version": found.get("version"),
                        "status": found.get("status"),
                        "bbox": found.get("bbox"),
                        "readings": [
                            r.get("raw_text") for r in found.get("observations", ())
                        ],
                    },
                )
                bindings, issues = select_heading_bindings(
                    captured, [structure], blocks, {}, folder, {}, source_line_map=lines
                )
            self.assertEqual(issues, [])
            self.assertEqual(
                [(row["cpd"], row["structure_id"]) for row in bindings],
                [("Compound 029B", "S1")],
            )
            self.assertEqual(bindings[0]["accuracy_status"], "confirmed")


if __name__ == "__main__":
    unittest.main()
