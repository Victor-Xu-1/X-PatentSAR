"""Fragmented caption detections need pixel reading, never string ID repair."""

import unittest
from unittest.mock import Mock, patch

import fitz

from patent_sar_extractor.core.cell_ocr_observation import observe_cell
from patent_sar_extractor.core.page_ocr_cache import get_ocr_engine
from patent_sar_extractor.core.table_cells import _normalize, read_cell
from tests.test_undetected_caption_lines import caption_pixels


def detection(text, left, right, top=0, bottom=46):
    return [[[left, top], [right, top], [right, bottom], [left, bottom]], text, 0.99]


class FragmentedCaptionLineTests(unittest.TestCase):
    def test_nonoverlapping_jittered_fragments_are_read_as_one_original_line(self):
        fragments = [
            detection("Compound", 4, 150),
            detection("4", 160, 190, 9),
            detection("7", 200, 292),
        ]
        engine = Mock(side_effect=[(fragments, 0), ([["Compound 47", 0.99]], 0)])
        observed = observe_cell(caption_pixels(), "label", 400, engine, _normalize)
        self.assertEqual(observed.value, "47")
        self.assertEqual(observed.raw_text, "Compound 47")
        self.assertEqual(engine.call_count, 2)
        self.assertFalse(engine.call_args.kwargs["use_det"])
        self.assertEqual(len(observed.detection_parts), 3)
        self.assertEqual(observed.parts[0]["method"], "complete_line_recognition")

    def test_complete_conflicting_detector_caption_is_not_overruled(self):
        fragments = [
            detection("Compound 48", 4, 190),
            detection("*", 200, 292),
        ]
        engine = Mock(side_effect=[(fragments, 0), ([["Compound 47", 0.99]], 0)])
        observed = observe_cell(caption_pixels(), "label", 400, engine, _normalize)
        self.assertEqual(observed.value, "")
        self.assertEqual(observed.raw_text, "Compound 47")
        self.assertEqual(observed.detection_parts[0]["text"], "Compound 48")

    def test_repeated_or_reversed_fragments_cannot_borrow_substring_membership(self):
        for first, second in (("4", "4"), ("7", "4"), ("4", "8")):
            fragments = [
                detection("Compound", 4, 150),
                detection(first, 160, 190, 9),
                detection(second, 200, 292),
            ]
            engine = Mock(side_effect=[(fragments, 0), ([["Compound 47", 0.99]], 0)])
            observed = observe_cell(caption_pixels(), "label", 400, engine, _normalize)
            with self.subTest(first=first, second=second):
                self.assertEqual(observed.value, "")
                self.assertEqual(observed.raw_text, "Compound 47")

    def test_fragmented_prefix_does_not_hide_repeated_digits_or_nonfinal_role(self):
        for words in (
            ("Com", "pound", "4", "4"),
            ("Intermediate", "Compound", "4", "7"),
        ):
            fragments = [
                detection(word, 4 + index * 70, 60 + index * 70)
                for index, word in enumerate(words)
            ]
            engine = Mock(side_effect=[(fragments, 0), ([["Compound 47", 0.99]], 0)])
            observed = observe_cell(caption_pixels(), "label", 400, engine, _normalize)
            with self.subTest(words=words):
                self.assertEqual(observed.value, "")


class FragmentedCaptionNativeTests(unittest.TestCase):
    def test_existing_engine_reads_original_pixels_after_controlled_detector_fragmentation(
        self,
    ):
        engine = get_ocr_engine()[1]
        complete_reads = []

        def fragmented(image, **options):
            if options.get("use_det", True):
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
        self.assertTrue(
            all(len(o["detection_parts"]) == 5 for o in reading.observations[1:])
        )
        self.assertTrue(
            all(
                o["parts"][0]["method"] == "complete_line_recognition"
                for o in reading.observations[1:]
            )
        )


if __name__ == "__main__":
    unittest.main()
