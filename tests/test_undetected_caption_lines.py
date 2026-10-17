"""Missing detector observations cannot erase bounded original caption ink."""

import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import fitz
import numpy as np

from patent_sar_extractor.core.binding_spatial import collect_spatial_bindings
from patent_sar_extractor.core.cell_identity_proof import (
    confirmed_identity_readings as _confirmed_observations,
)
from patent_sar_extractor.core.cell_ocr_observation import observe_cell
from patent_sar_extractor.core.page_ocr_cache import get_ocr_engine
from patent_sar_extractor.core.pipeline_rules import annotate_binding_accuracy
from patent_sar_extractor.core.table_cells import _normalize, read_cell


def caption_pixels(*, multiline=False, solid=False):
    image = np.full((130 if multiline else 60, 340, 3), 255, dtype=np.uint8)
    if solid:
        image[10:50, 10:310] = 0
    else:
        for left in range(12, 290, 18):
            image[15:46, left : left + 8] = 0
        if multiline:
            for left in range(12, 220, 18):
                image[87:118, left : left + 8] = 0
    return image


def missed_engine(text="Compound 42", score=0.99):
    return Mock(side_effect=[([], 0), ([[text, score]], 0)])


class UndetectedCaptionTests(unittest.TestCase):
    def observe(self, *, text="Compound 42", score=0.99, image=None):
        engine = missed_engine(text, score)
        reading = observe_cell(
            caption_pixels() if image is None else image,
            "label",
            400,
            engine,
            _normalize,
        )
        return reading, engine

    def test_original_single_line_is_observed_even_when_detector_finds_nothing(self):
        for text, expected in (("Compound 42", "42"), ("Example 008B", "008B")):
            with self.subTest(text=text):
                reading, engine = self.observe(text=text)
                self.assertEqual(reading.value, expected)
                self.assertEqual(reading.raw_text, text)
                self.assertEqual(reading.detection_parts, ())
                self.assertEqual(engine.call_count, 2)
                self.assertFalse(engine.call_args.kwargs["use_det"])
                evidence = reading.evidence(400, (10, 10, 100, 30))
                self.assertEqual(
                    evidence["physical_caption_line"]["status"], "observed"
                )
                self.assertEqual(reading.parts[0]["method"], "undetected_caption_line")

    def test_saved_source_proof_rechecks_complete_line_and_all_original_conflicts(self):
        reading, _ = self.observe()
        original = {"method": "page_ocr_cell", "text": "Compound 42"}
        evidence = reading.evidence(400, (10, 10, 100, 30))
        self.assertTrue(_confirmed_observations("42", [original, evidence]))
        for altered in (
            {"physical_caption_line": None},
            {"physical_caption_line": {}},
            {"detection_parts": [{"text": "Compound 43"}]},
            {"confidence": True},
            {"raw_text": "Compound 43"},
            {"ink_crop_pixels": [0, 0, 300, 300]},
            {"render_dpi": 300},
        ):
            packet = copy.deepcopy(evidence)
            packet.update(altered)
            with self.subTest(altered=altered):
                self.assertFalse(_confirmed_observations("42", [original, packet]))
        for method in ("page_ocr_cell", "native_cell"):
            self.assertFalse(
                _confirmed_observations(
                    "42", [{"method": method, "text": "Compound 43"}, evidence]
                )
            )

    def test_formal_caption_admission_cannot_ignore_a_changed_original_reading(self):
        reading, _ = self.observe()
        packet = reading.evidence(400, (10, 180, 160, 195))
        binding = {
            "cpd": "Compound 42",
            "structure_id": "controlled-source-42",
            "page_no": 1,
            "struct_x0": 10,
            "struct_y0": 30,
            "struct_x1": 160,
            "struct_y1": 180,
            "binding_rule": "direct_structure_label",
            "visible_label_candidates": [{"label": "42", "source": "pdf_clip"}],
            "exact_caption_evidence": {
                "bbox": [10, 180, 160, 195],
                "page_no": 1,
                "ownership": {},
                "observations": [
                    {"method": "page_ocr_cell", "text": "Compound 42"},
                    packet,
                ],
            },
        }
        self.assertEqual(
            annotate_binding_accuracy(binding)["accuracy_status"], "confirmed"
        )
        for mutation in (
            lambda value: value["exact_caption_evidence"]["observations"][1].update(
                physical_caption_line=None
            ),
            lambda value: value["exact_caption_evidence"].update(page_no=True),
            lambda value: value["exact_caption_evidence"].update(
                bbox=[300, 600, 400, 620]
            ),
            lambda value: value["exact_caption_evidence"]["observations"][0].update(
                text="Compound 43"
            ),
        ):
            changed = copy.deepcopy(binding)
            mutation(changed)
            result = annotate_binding_accuracy(changed)
            self.assertTrue(result["fail_closed"], changed)
            self.assertEqual(result["accuracy_status"], "review_required")

    def test_multiline_solid_or_tall_input_cannot_be_guessed_as_a_caption(self):
        for image in (
            caption_pixels(multiline=True),
            caption_pixels(solid=True),
            np.zeros((180, 340, 3), dtype=np.uint8),
            np.zeros((2000, 4001, 3), dtype=np.uint8),
        ):
            with self.subTest(shape=image.shape):
                reading, engine = self.observe(image=image)
                self.assertEqual(reading.value, "")
                self.assertEqual(engine.call_count, 1)

    def test_low_or_malformed_confidence_and_unknown_prose_stay_unconfirmed(self):
        for text, score in (
            ("Compound 42", 0.84),
            ("Compound 42", True),
            ("Compound 42", float("nan")),
            ("Compound 42; Intermediate 43", 0.99),
        ):
            with self.subTest(text=text, score=score):
                reading, _ = self.observe(text=text, score=score)
                self.assertEqual(reading.value, "")

    def test_blank_and_noncaption_sources_do_not_start_the_recovery_read(self):
        engine = Mock(return_value=([], 0))
        blank = np.full((60, 340, 3), 255, dtype=np.uint8)
        self.assertEqual(
            observe_cell(blank, "label", 400, engine, _normalize).value, ""
        )
        engine.assert_not_called()
        observe_cell(caption_pixels(), "number", 400, engine, _normalize)
        self.assertEqual(engine.call_count, 1)

    def test_new_caption_rule_requires_original_proof_even_if_flags_claim_success(self):
        result = annotate_binding_accuracy(
            {
                "cpd": "Compound 42",
                "structure_id": "controlled-source-42",
                "page_no": 1,
                "binding_rule": "original_caption_cell",
                "visible_label_candidates": [{"label": "42", "source": "pdf_clip"}],
                "accuracy_status": "confirmed",
                "fail_closed": False,
            }
        )
        self.assertTrue(result["fail_closed"])
        self.assertEqual(result["accuracy_status"], "review_required")


class UndetectedCaptionNativeTests(unittest.TestCase):
    def test_existing_engine_recognizes_controlled_original_when_detection_is_missing(
        self,
    ):
        engine = get_ocr_engine()
        self.assertIsNotNone(engine)
        self.assertEqual(engine[0], "rapidocr")
        for text, expected, font in (
            ("Compound 42", "42", "helv"),
            ("Compound 581", "581", "tibo"),
            ("Compound 126B", "126B", "hebo"),
        ):
            calls = []

            def missing_detection(image, *, call_log=calls, **options):
                call_log.append(options)
                return ([], 0) if options["use_det"] else engine[1](image, **options)

            with self.subTest(text=text), fitz.open() as doc:
                page = doc.new_page()
                page.insert_text((90, 110), text, fontsize=9, fontname=font)
                with patch(
                    "patent_sar_extractor.core.table_cells.get_ocr_engine",
                    return_value=("rapidocr", missing_detection),
                ):
                    reading = read_cell(page, (70, 95, 265, 125), [], "label", False)
                self.assertEqual(reading.value, expected, reading.observations)
                self.assertFalse(reading.needs_review)
                self.assertEqual(len(calls), 4)
                self.assertTrue(_confirmed_observations(expected, reading.observations))

    def test_raster_catalog_keeps_exact_caption_proof_through_the_real_source_gate(
        self,
    ):
        engine = get_ocr_engine()[1]

        def missing_detection(image, **options):
            return ([], 0) if options["use_det"] else engine(image, **options)

        with (
            fitz.open() as source,
            fitz.open() as raster,
            tempfile.TemporaryDirectory() as temporary,
        ):
            page = source.new_page(width=400, height=350)
            xs, ys = (50, 200, 350), (100, 125, 225)
            for x in xs:
                page.draw_line((x, ys[0]), (x, ys[-1]))
            for y in ys:
                page.draw_line((xs[0], y), (xs[-1], y))
            page.insert_text((50, 85), "Table 17. Compounds", fontsize=10)
            structures = []
            for index, label in enumerate(("42", "581")):
                x = xs[index] + 30
                page.insert_text((x, 117), "Compound " + label, fontsize=9)
                page.draw_polyline([(x, 150), (x + 45, 160), (x + 20, 195)])
                structures.append(
                    {
                        "id": "controlled-" + label,
                        "idx": index,
                        "page_no": 1,
                        "x0": x,
                        "y0": 145,
                        "x1": x + 60,
                        "y1": 205,
                    }
                )
            raster_page = raster.new_page(width=400, height=350)
            raster_page.insert_image(
                raster_page.rect, stream=page.get_pixmap(dpi=240).tobytes("png")
            )
            for structure in structures:
                path = Path(temporary) / (structure["id"] + ".png")
                crop = fitz.Rect([structure[key] for key in ("x0", "y0", "x1", "y1")])
                raster_page.get_pixmap(clip=crop, dpi=200).save(path)
                structure["image_path"] = str(path)
            with patch(
                "patent_sar_extractor.core.table_cells.get_ocr_engine",
                return_value=("rapidocr", missing_detection),
            ):
                result = collect_spatial_bindings(
                    raster, structures, {0: ""}, {0: []}, [], {}, frozenset()
                )
            self.assertFalse(result.conflicts, result.conflicts)
            bindings = result.catalogue()
            self.assertEqual(
                {row["cpd"] for row in bindings}, {"Compound 42", "Compound 581"}
            )
            for row in bindings:
                self.assertEqual(row["binding_rule"], "original_caption_cell")
                self.assertEqual(row["accuracy_status"], "confirmed", row)
                self.assertTrue(
                    all(
                        observed["physical_caption_line"]["status"] == "observed"
                        for observed in row["exact_caption_evidence"]["observations"][
                            1:
                        ]
                    )
                )
                for altered in (
                    {"direction": "below"},
                    {"structure_page_no": True},
                    {"structure_cell": [300, 600, 400, 800]},
                ):
                    changed = copy.deepcopy(row)
                    changed["exact_caption_evidence"]["ownership"].update(altered)
                    self.assertTrue(annotate_binding_accuracy(changed)["fail_closed"])
