"""Controlled original-source renders; no private patent or replacement job."""

import unittest

import fitz

from patent_sar_extractor.core.table_cells import read_cell


class CaptionCellNativeTests(unittest.TestCase):
    def test_existing_engine_reads_small_single_line_caption(self):
        self.check_caption(["Compound 73"], "73", 9)

    def test_existing_engine_reads_split_literal_first_elution_note(self):
        self.check_caption(["Compound 84", "*first eluting", "isomer"], "84", 10)

    def test_existing_engine_reads_second_elution_note_without_identity_rewrite(self):
        self.check_caption(["Compound 95 *second", "eluting isomer"], "95", 10)

    def test_existing_engine_does_not_merge_two_original_ids(self):
        self.check_caption(["Compound 73", "Compound 74"], "", 10)

    def check_caption(self, lines, expected, size):
        with fitz.open() as doc:
            page = doc.new_page()
            for index, text in enumerate(lines):
                page.insert_text((90, 110 + index * 14), text, fontsize=size)
            reading = read_cell(
                page, (70, 95, 265, 110 + len(lines) * 14), [], "label", False
            )
        if expected:
            self.assertEqual(reading.value, expected, reading.observations)
            self.assertFalse(reading.needs_review, reading.observations)
        else:
            self.assertTrue(reading.needs_review)
        self.assertEqual(len(reading.observations), 3)
        self.assertTrue(all(o["raw_text"] for o in reading.observations[1:]))
        self.assertTrue(all(o["parts"] for o in reading.observations[1:]))
