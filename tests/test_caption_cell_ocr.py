import unittest
from unittest.mock import Mock, patch

import numpy as np

from patent_sar_extractor.core.table_cells import _ocr_cell


class CaptionCellOCRTests(unittest.TestCase):
    def test_multiline_caption_is_not_squeezed_into_single_text_line(self):
        engine = Mock(
            return_value=(
                [
                    [
                        [[0, 0], [300, 0], [300, 40], [0, 40]],
                        "Compound 73 *first",
                        0.99,
                    ],
                    [
                        [[0, 70], [300, 70], [300, 110], [0, 110]],
                        "eluting isomer",
                        0.98,
                    ],
                ],
                0,
            )
        )
        image = np.zeros((120, 320, 3), dtype=np.uint8)
        with (
            patch(
                "patent_sar_extractor.core.table_cells.get_ocr_engine",
                return_value=("rapidocr", engine),
            ),
            patch(
                "patent_sar_extractor.core.table_cells.cell_image", return_value=image
            ),
        ):
            value, _ = _ocr_cell(None, (0, 0, 100, 30), "label", 400)
        self.assertEqual(value, "73")
        self.assertTrue(engine.call_args.kwargs["use_det"])

    def test_two_printed_identifiers_in_one_cell_are_not_merged(self):
        engine = Mock(
            return_value=(
                [
                    [[[0, 0], [300, 0], [300, 40], [0, 40]], "Compound 73", 0.99],
                    [[[0, 70], [300, 70], [300, 110], [0, 110]], "Compound 74", 0.98],
                ],
                0,
            )
        )
        with (
            patch(
                "patent_sar_extractor.core.table_cells.get_ocr_engine",
                return_value=("rapidocr", engine),
            ),
            patch(
                "patent_sar_extractor.core.table_cells.cell_image",
                return_value=np.zeros((120, 320, 3), dtype=np.uint8),
            ),
        ):
            self.assertEqual(_ocr_cell(None, (0, 0, 100, 30), "label", 400)[0], "")
