"""Original caption location and actual recognition window are different facts."""

import copy
import unittest
from unittest.mock import patch

import fitz

from patent_sar_extractor.core.binding_spatial import collect_spatial_bindings
from patent_sar_extractor.core.caption_binding_proof import (
    valid_caption_binding_evidence,
)
from patent_sar_extractor.core.caption_original_replay import (
    original_caption_source_errors,
)
from patent_sar_extractor.core.caption_source_windows import (
    caption_read_window,
    caption_windows,
    original_caption_read_window,
)
from patent_sar_extractor.core.source_geometry import SourceTokens, source_layout


class CaptionObservationWindowTests(unittest.TestCase):
    def source(self, label="73B", *, raster=True, caption_x=90):
        authored = fitz.open()
        page = authored.new_page(width=500, height=300)
        left, right = max(0, caption_x - 30), min(500, caption_x + 130)
        page.draw_polyline(
            [(left + 10, 100), (left + 30, 80), (right - 30, 100), (right - 10, 130)]
        )
        page.insert_text((caption_x, 175), "Compound " + label, fontsize=10)
        words = page.get_text("words")
        bounds = [
            min(w[0] for w in words),
            min(w[1] for w in words),
            max(w[2] for w in words),
            max(w[3] for w in words),
        ]
        document = authored
        if raster:
            document = fitz.open()
            scanned = document.new_page(width=500, height=300)
            scanned.insert_image(
                scanned.rect,
                stream=page.get_pixmap(matrix=fitz.Matrix(4, 4), alpha=False).tobytes(
                    "png"
                ),
            )
            authored.close()
        self.addCleanup(document.close)

        def tokens(page, **_options):
            layout = source_layout(page)
            if not raster:
                return SourceTokens(layout.native, layout)
            return SourceTokens(
                [
                    {
                        "text": "Compound " + label,
                        "bbox": bounds,
                        "x": (bounds[0] + bounds[2]) / 2,
                        "y": (bounds[1] + bounds[3]) / 2,
                        "confidence": 0.99,
                        "source": "raster",
                        "geometry_space": "rendered",
                    }
                ],
                layout,
                layout.raster_bounds,
            )

        def reader(image, *, use_det, use_cls):
            # Controlled text carrier; rendering, crop, confidence/row proof,
            # ownership, serialization and original readback are real code.
            if use_det:
                return [], None
            return [["Compound " + label, 0.99]], None

        structure = {
            "id": "ORIGINAL-DIAGRAM",
            "idx": 0,
            "page_no": 1,
            "x0": left,
            "x1": right,
            "y0": 60,
            "y1": 175,
            "image_path": "controlled.png",
        }
        with (
            patch("patent_sar_extractor.core.binding_spatial.page_tokens", tokens),
            patch(
                "patent_sar_extractor.core.table_cells.get_ocr_engine",
                return_value=("rapidocr", reader),
            ),
        ):
            result = collect_spatial_bindings(
                document, [structure], {0: ""}, {}, [], {}, frozenset()
            )
        self.assertEqual(len(result.candidates), 1, result.conflicts)
        return document, copy.deepcopy(dict(result.candidates[0].binding))

    def test_normal_free_caption_writer_replays_its_actual_original_pixels(self):
        for label in ("73B", "108A"):
            with self.subTest(label=label):
                document, binding = self.source(label)
                self.assertTrue(valid_caption_binding_evidence(binding))
                reading = next(
                    o
                    for o in binding["exact_caption_evidence"]["observations"]
                    if o["method"] == "cell_ocr_400dpi"
                )
                self.assertNotEqual(
                    binding["exact_caption_evidence"]["bbox"], reading["bbox"]
                )
                self.assertEqual(
                    original_caption_source_errors(document, [binding]), []
                )

    def test_native_caption_uses_the_same_source_window_contract(self):
        document, binding = self.source(raster=False)
        self.assertTrue(valid_caption_binding_evidence(binding))
        self.assertEqual(original_caption_source_errors(document, [binding]), [])

    def test_missing_mixed_or_changed_windows_never_upgrade_a_saved_caption(self):
        document, baseline = self.source()
        for mutation in (
            "missing",
            "use_anchor",
            "move_anchor",
            "bool",
            "nan",
            "huge_integer",
            "mixed_attempt",
            "malformed_method",
        ):
            with self.subTest(mutation=mutation):
                binding = copy.deepcopy(baseline)
                packet = binding["exact_caption_evidence"]
                if mutation == "missing":
                    packet.pop("reading_bbox")
                elif mutation == "use_anchor":
                    packet["reading_bbox"] = list(packet["bbox"])
                elif mutation == "move_anchor":
                    packet["bbox"][0] += 1
                elif mutation == "bool":
                    packet["reading_bbox"][0] = True
                elif mutation == "nan":
                    packet["reading_bbox"][2] = float("nan")
                elif mutation == "huge_integer":
                    packet["reading_bbox"][2] = 10**400
                elif mutation == "mixed_attempt":
                    packet["observations"][0]["bbox"][0] += 1
                else:
                    packet["observations"][0]["method"] = []
                self.assertFalse(valid_caption_binding_evidence(binding))
                self.assertTrue(original_caption_source_errors(document, [binding]))

    def test_changed_original_pixels_are_not_excused_by_the_separate_window(self):
        document, binding = self.source()
        self.assertEqual(original_caption_source_errors(document, [binding]), [])
        x, y = binding["exact_caption_evidence"]["reading_bbox"][:2]
        document[0].draw_rect(
            fitz.Rect(x + 2, y + 2, x + 3, y + 3), color=None, fill=(0, 0, 0)
        )
        self.assertTrue(original_caption_source_errors(document, [binding]))

    def test_actual_page_clipping_not_a_saved_smaller_window_owns_the_edge(self):
        for x in (2, 428):
            with self.subTest(caption_x=x):
                document, binding = self.source(caption_x=x)
                packet = binding["exact_caption_evidence"]
                self.assertEqual(
                    original_caption_source_errors(document, [binding]), []
                )
                self.assertEqual(
                    packet["reading_bbox"][0] if x == 2 else packet["reading_bbox"][2],
                    0 if x == 2 else 500,
                )
                changed = copy.deepcopy(packet)
                changed["reading_bbox"][2] -= 0.5
                for reading in changed["observations"]:
                    reading["bbox"] = list(changed["reading_bbox"])
                self.assertIsNotNone(caption_windows(changed))
                with self.assertRaises(ValueError):
                    original_caption_read_window(changed, (500, 300))

    def test_native_source_tokens_cannot_be_relocated_while_keeping_the_text(self):
        document, binding = self.source(raster=False)
        source = binding["exact_caption_evidence"]["observations"][0][
            "source_observation"
        ]
        source["tokens"][0]["bbox"][0] += 0.5
        source["tokens"][0]["x"] += 0.25
        self.assertTrue(valid_caption_binding_evidence(binding))
        self.assertTrue(original_caption_source_errors(document, [binding]))

    def test_untrusted_anchor_and_page_coordinates_refuse_without_overflow(self):
        for value in (10**400, -(10**400), float("nan"), float("inf"), True):
            with self.subTest(value_type=type(value).__name__):
                with self.assertRaises(ValueError):
                    caption_read_window([value, 10, 20, 30], (100, 100))
                with self.assertRaises(ValueError):
                    caption_read_window([10, 10, 20, 30], (value, 100))
