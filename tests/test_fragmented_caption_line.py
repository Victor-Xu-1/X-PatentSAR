"""Fragmented caption detections need pixel reading, never string ID repair."""

import unittest
from unittest.mock import Mock, patch

import fitz

from patent_sar_extractor.core.caption_reading_proof import confirmed_caption_readings
from patent_sar_extractor.core.cell_ocr_observation import observe_cell
from patent_sar_extractor.core.page_ocr_cache import get_ocr_engine
from patent_sar_extractor.core.table_cells import _normalize, read_cell
from tests.test_undetected_caption_lines import caption_pixels


def detection(text, left, right, top=0, bottom=46):
    return [[[left, top], [right, top], [right, bottom], [left, bottom]], text, 0.99]


class FragmentedCaptionLineTests(unittest.TestCase):
    def test_multiline_caption_reads_the_complete_fragmented_original_row(self):
        fragments = [
            detection("Compound", 4, 150),
            detection("4", 160, 190, 9),
            detection("7", 200, 265),
            detection("first eluting isomer", 4, 230, 80, 111),
        ]
        engine = Mock(side_effect=[(fragments, 0), ([["Compound 47", 0.99]], 0)])
        observed = observe_cell(
            caption_pixels(multiline=True), "label", 400, engine, _normalize
        )
        self.assertEqual(observed.value, "47")
        self.assertEqual(observed.raw_text, "Compound 47 first eluting isomer")
        self.assertEqual(engine.call_count, 2)
        self.assertFalse(engine.call_args.kwargs["use_det"])
        self.assertEqual(len(observed.detection_parts), 4)
        self.assertEqual(observed.parts[0]["method"], "complete_line_recognition")

    def test_complete_conflicting_detector_caption_is_not_overruled(self):
        fragments = [
            detection("Compound 48", 4, 190),
            detection("*", 200, 265),
            detection("first eluting isomer", 4, 230, 80, 111),
        ]
        engine = Mock(side_effect=[(fragments, 0), ([["Compound 47", 0.99]], 0)])
        observed = observe_cell(
            caption_pixels(multiline=True), "label", 400, engine, _normalize
        )
        self.assertEqual(observed.value, "")
        self.assertEqual(observed.raw_text, "Compound 47 first eluting isomer")
        self.assertEqual(observed.detection_parts[0]["text"], "Compound 48")

    def test_repeated_or_reversed_fragments_cannot_borrow_substring_membership(self):
        for first, second in (("4", "4"), ("7", "4"), ("4", "8")):
            fragments = [
                detection("Compound", 4, 150),
                detection(first, 160, 190, 9),
                detection(second, 200, 265),
                detection("first eluting isomer", 4, 230, 80, 111),
            ]
            engine = Mock(side_effect=[(fragments, 0), ([["Compound 47", 0.99]], 0)])
            observed = observe_cell(
                caption_pixels(multiline=True), "label", 400, engine, _normalize
            )
            with self.subTest(first=first, second=second):
                self.assertEqual(observed.value, "")
                self.assertEqual(observed.raw_text, "Compound 47 first eluting isomer")

    def test_fragmented_prefix_does_not_hide_repeated_digits_or_nonfinal_role(self):
        for words in (
            ("Com", "pound", "4", "4"),
            ("Intermediate", "Compound", "4", "7"),
        ):
            fragments = [
                detection(word, 4 + index * 70, 60 + index * 70)
                for index, word in enumerate(words)
            ]
            fragments.append(detection("first eluting isomer", 4, 230, 80, 111))
            engine = Mock(side_effect=[(fragments, 0), ([["Compound 47", 0.99]], 0)])
            observed = observe_cell(
                caption_pixels(multiline=True), "label", 400, engine, _normalize
            )
            with self.subTest(words=words):
                self.assertEqual(observed.value, "")


class FragmentedCaptionNativeTests(unittest.TestCase):
    def test_actual_whole_pixel_read_preserves_independent_page_identifier_conflict(
        self,
    ):
        engine = get_ocr_engine()[1]
        for original_number, accepted in (("126B", True), ("126C", False)):
            observed_engine = Mock(side_effect=engine)

            with fitz.open() as document:
                page = document.new_page()
                page.insert_text(
                    (90, 110), "Compound 126B", fontsize=10, fontname="hebo"
                )
                with patch(
                    "patent_sar_extractor.core.table_cells.get_ocr_engine",
                    return_value=("rapidocr", observed_engine),
                ):
                    reading = read_cell(
                        page,
                        (70, 95, 265, 124),
                        [{"text": "Compound " + original_number, "x": 90, "y": 105}],
                        "label",
                        False,
                    )
            with self.subTest(original_number=original_number):
                self.assertEqual(
                    reading.value, "126B" if accepted else "", reading.observations
                )
                self.assertEqual(
                    reading.needs_review, not accepted, reading.observations
                )
                self.assertEqual(
                    confirmed_caption_readings(
                        "126B", reading.observations, {}, 1, [70, 95, 265, 124]
                    ),
                    accepted,
                )
                self.assertTrue(
                    all(
                        not call.kwargs["use_det"]
                        for call in observed_engine.call_args_list
                    )
                )
                self.assertEqual(
                    reading.observations[0]["text"], "Compound " + original_number
                )

    def test_existing_engine_reads_complete_caption_before_fragment_detection(
        self,
    ):
        engine = get_ocr_engine()[1]
        complete_reads = []
        detections = []

        def fragmented(image, **options):
            if options.get("use_det", True):
                detections.append(image.shape)
                height, width = image.shape[:2]
                words = ("Compound", "1", "2", "6", "B")
                return [
                    detection(
                        word,
                        1 + i * width / 5,
                        (i + 1) * width / 5 - 1,
                        top=1 + i % 2,
                        bottom=height - 1,
                    )
                    for i, word in enumerate(words)
                ], 0
            result, duration = engine(image, **options)
            complete_reads.append(result)
            return result, duration

        with fitz.open() as doc:
            page = doc.new_page()
            page.insert_text((90, 110), "Compound 126B", fontsize=10, fontname="hebo")
            with patch(
                "patent_sar_extractor.core.table_cells.get_ocr_engine",
                return_value=("rapidocr", fragmented),
            ):
                reading = read_cell(page, (70, 95, 265, 124), [], "label", False)
        self.assertEqual(reading.value, "126B", reading.observations)
        self.assertFalse(reading.needs_review, reading.observations)
        self.assertEqual(len(complete_reads), 2)
        self.assertEqual(detections, [])
        self.assertTrue(
            all(o["detection_parts"] == [] for o in reading.observations[1:])
        )
        self.assertTrue(
            all(
                o["parts"][0]["method"] == "physical_caption_line"
                for o in reading.observations[1:]
            )
        )


if __name__ == "__main__":
    unittest.main()
