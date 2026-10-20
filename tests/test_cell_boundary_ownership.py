"""Complete original glyph ownership, not a text/model quality benchmark."""

import copy
import json
import unittest
from contextlib import contextmanager
from unittest.mock import Mock, patch

import fitz
import numpy as np

from patent_sar_extractor.core.activity_header_columns import observe_header_columns
from patent_sar_extractor.core.cell_frame_proof import original_cell_frame_matches
from patent_sar_extractor.core.source_cell_tokens import cell_text, crosses_cell
from patent_sar_extractor.core.source_geometry import (
    SourceLayout,
    SourceTokens,
    source_layout,
)
from patent_sar_extractor.core.source_observations import (
    project_source_observation,
    source_cell_observation,
    source_claim_runs,
    source_observation_status,
)
from patent_sar_extractor.core.table_cells import cell_image, observe_original_cell

BOUNDS = [60.0, 60.0, 240.0, 150.0]


def pixels(page, dpi):
    pixmap = page.get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72), alpha=False)
    return np.frombuffer(pixmap.samples, np.uint8).reshape(
        pixmap.height, pixmap.width, 3
    )


def ink(image):
    return image.min(axis=2) < 180


def ink_bounds(image, dpi):
    ys, xs = np.where(ink(image))
    if not len(xs):
        raise AssertionError("Controlled source unexpectedly contains no ink")
    return np.array([xs.min(), ys.min(), xs.max() + 1, ys.max() + 1]) * 72 / dpi


@contextmanager
def word_at_edge(text, edge, gap, dpi, *, font="helv", size=8):
    """Place visible glyph ink, not font ascender/descender padding, at an edge."""
    start = np.array([100.0, 100.0])
    with fitz.open() as draft:
        page = draft.new_page(width=300, height=220)
        page.insert_text(start.tolist(), text, fontname=font, fontsize=size)
        original = ink_bounds(pixels(page, dpi), dpi)
    index = {"left": 0, "top": 1, "right": 2, "bottom": 3}[edge]
    target = BOUNDS[index] + (gap if index < 2 else -gap)
    start[index % 2] += target - original[index]
    with fitz.open() as source:
        page = source.new_page(width=300, height=220)
        page.insert_text(start.tolist(), text, fontname=font, fontsize=size)
        data = source.tobytes()
    with fitz.open(stream=data, filetype="pdf") as document:
        yield document, document[0]


class CellBoundaryOwnershipTests(unittest.TestCase):
    def test_unruled_cells_do_not_cut_contained_identifier_value_or_unit_ink(self):
        for dpi in (400, 600):
            for text in ("Compound 37B", "<0.5 nM", "DC50 pM"):
                for edge in ("left", "right", "top", "bottom"):
                    with (
                        self.subTest(dpi=dpi, text=text, edge=edge),
                        word_at_edge(text, edge, 0.5, dpi) as (_, page),
                    ):
                        source = pixels(page, dpi)
                        box = ink_bounds(source, dpi)
                        self.assertTrue(np.all(box[:2] >= BOUNDS[:2]))
                        self.assertTrue(np.all(box[2:] <= BOUNDS[2:]))
                        observed = cell_image(page, BOUNDS, dpi)
                        self.assertEqual(
                            int(ink(observed).sum()),
                            int(ink(source).sum()),
                            "A fixed inset must not silently discard original glyph pixels",
                        )

    def test_clear_unruled_interior_still_preserves_all_original_ink(self):
        for dpi in (400, 600):
            for edge in ("left", "right", "top", "bottom"):
                with (
                    self.subTest(dpi=dpi, edge=edge),
                    word_at_edge("IC50 pM", edge, 4, dpi) as (_, page),
                ):
                    self.assertEqual(
                        int(ink(cell_image(page, BOUNDS, dpi)).sum()),
                        int(ink(pixels(page, dpi)).sum()),
                    )

    def test_crossing_guards_include_intersections_with_centres_outside(self):
        for box in (
            [50, 90, 68, 100],
            [232, 90, 250, 100],
            [100, 50, 120, 68],
            [100, 142, 120, 160],
        ):
            token = {
                "text": "37B",
                "bbox": box,
                "x": (box[0] + box[2]) / 2,
                "y": (box[1] + box[3]) / 2,
            }
            with self.subTest(box=box):
                self.assertTrue(crosses_cell([token], BOUNDS))
                self.assertEqual(
                    cell_text([token], BOUNDS),
                    "",
                    "A conflict witness is not ownership of a neighbour's text",
                )

    def test_disjoint_or_only_touching_neighbour_is_not_a_crossing(self):
        for box in (
            [30, 90, 60, 100],
            [240, 90, 270, 100],
            [100, 30, 120, 60],
            [100, 150, 120, 170],
        ):
            with self.subTest(box=box):
                self.assertFalse(
                    crosses_cell(
                        [
                            {
                                "bbox": box,
                                "x": (box[0] + box[2]) / 2,
                                "y": (box[1] + box[3]) / 2,
                                "text": "neighbour",
                            }
                        ],
                        BOUNDS,
                    )
                )

    def test_outside_centre_witness_survives_serialization_without_claiming_text(self):
        for box in (
            [50, 90, 68, 100],
            [232, 90, 250, 100],
            [100, 50, 120, 68],
            [100, 142, 120, 160],
        ):
            token = {
                "text": "37B",
                "bbox": box,
                "x": (box[0] + box[2]) / 2,
                "y": (box[1] + box[3]) / 2,
                "confidence": 0.99,
            }
            with self.subTest(box=box):
                tokens = SourceTokens([token], SourceLayout((), None))
                packet = json.loads(json.dumps(source_cell_observation(tokens, BOUNDS)))
                self.assertEqual(packet["tokens"], [])
                self.assertEqual(len(packet["boundary_tokens"]), 1)
                self.assertEqual(packet["text"], "")
                self.assertEqual(
                    source_observation_status(packet, BOUNDS, ""), "unqualified"
                )
                self.assertEqual(source_claim_runs(packet), ())
                self.assertEqual(project_source_observation(packet, BOUNDS), packet)
                changed = copy.deepcopy(packet)
                changed["status"] = "empty"
                self.assertEqual(
                    source_observation_status(changed, BOUNDS, ""), "invalid"
                )
                changed = copy.deepcopy(packet)
                del changed["boundary_tokens"]
                self.assertEqual(
                    source_observation_status(changed, BOUNDS, ""), "invalid"
                )

    def test_projected_cell_keeps_new_boundary_witness_not_neighbour_ownership(self):
        token = {
            "text": "12",
            "bbox": [180, 80, 210, 100],
            "x": 195,
            "y": 90,
            "confidence": 0.99,
        }
        parent = source_cell_observation(
            SourceTokens([token], SourceLayout((), None)), BOUNDS
        )
        self.assertEqual(source_observation_status(parent, BOUNDS, "12"), "qualified")
        child = project_source_observation(parent, [60, 60, 190, 150])
        self.assertEqual(child["tokens"], [])
        self.assertEqual(child["text"], "")
        self.assertEqual(len(child["boundary_tokens"]), 1)
        self.assertEqual(
            source_observation_status(child, child["bbox"], ""), "unqualified"
        )

    def test_complete_visible_header_is_not_rejected_for_font_box_padding(self):
        # The controlled reader isolates geometry: it does not test OCR quality,
        # supply a patent value, or authorize conflicting/scanned interpretations.
        for dpi in (400, 600):
            with (
                self.subTest(dpi=dpi),
                word_at_edge("DC50 nM", "top", 2, dpi, size=11) as (_, page),
            ):
                source = pixels(page, dpi)
                self.assertGreater(ink_bounds(source, dpi)[1], BOUNDS[1] + 1.2)
                layout = source_layout(page)
                tokens = SourceTokens(layout.native, layout)
                engine = Mock(return_value=([["DC50 nM", 0.999]], None))
                with patch(
                    "patent_sar_extractor.core.activity_header_columns.get_ocr_engine",
                    return_value=("rapidocr", engine),
                ):
                    result = observe_header_columns(
                        page, {"xs": [60, 240], "ys": [60, 150]}, 1, dpi, tokens
                    )
                self.assertEqual(result.columns[0]["raw_text"], "DC50 nM")
                self.assertTrue(result.verified[0], result.columns[0])

    def test_actual_original_replay_still_rejects_changed_source_or_frame(self):
        for dpi in (400, 600):
            with (
                self.subTest(dpi=dpi),
                word_at_edge("DC50 nM", "top", 8, dpi) as (document, page),
            ):
                reader = Mock(return_value=([["DC50 nM", 0.999]], None))
                observed = observe_original_cell(
                    page,
                    BOUNDS,
                    "header",
                    dpi,
                    reader,
                    lambda text, _kind: text.strip(),
                ).evidence(dpi, BOUNDS)
                self.assertTrue(original_cell_frame_matches(observed, page))
                changed = copy.deepcopy(observed)
                changed["source_frame"]["pixel_sha256"] = "0" * 64
                self.assertFalse(original_cell_frame_matches(changed, page))
                with fitz.open(stream=document.tobytes(), filetype="pdf") as other:
                    other[0].insert_text((120, 120), "Different", fontsize=8)
                    self.assertFalse(original_cell_frame_matches(observed, other[0]))
