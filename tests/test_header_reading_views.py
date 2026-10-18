"""Small printed original headers retain complete text without OCR dictionaries."""

import unittest

from patent_sar_extractor.core.activity_header_columns import observe_header_columns
from patent_sar_extractor.core.activity_header_identity import compact_header
from tests.test_header_physical_lines import scanned_headers


class HeaderReadingViewTests(unittest.TestCase):
    def test_small_serif_and_sans_originals_keep_all_fields_at_both_resolutions(self):
        for font, size in (("tibo", 4.8), ("tiro", 5.0), ("hebo", 5.0), ("heit", 5.2)):
            document, page, region, headers = scanned_headers(font, size)
            with document:
                for dpi in (400, 600):
                    with self.subTest(font=font, size=size, dpi=dpi):
                        observed = observe_header_columns(page, region, 1, dpi)
                        summary = [
                            (column["raw_text"], column["confidence"])
                            for column in observed.columns
                        ]
                        self.assertEqual(
                            tuple(map(compact_header, observed.matrix[0])),
                            tuple(
                                compact_header("\n".join(lines)) for lines in headers
                            ),
                            summary,
                        )
                        self.assertTrue(
                            all(column["text"] for column in observed.columns), summary
                        )
                        for column, verified in zip(
                            observed.columns, observed.verified, strict=True
                        ):
                            if column.get("detector_conflict"):
                                self.assertFalse(
                                    verified
                                )  # A better crop cannot overrule a known alternate literal.
                        self.assertTrue(
                            all(
                                "0.145" not in column["raw_text"]
                                for column in observed.columns
                            )
                        )

    def test_ambiguous_italic_source_cannot_be_promoted_by_padding_or_unit_guesses(
        self,
    ):
        # Positive automatic coverage for these low-resolution serif/monospace
        # inputs remains OPEN in the repair plan. This check proves only honest
        # refusal and conservation; it does not certify their text recognition.
        for font, size in (("tibi", 5.0), ("cobi", 5.5)):
            document, page, region, _headers = scanned_headers(font, size)
            with document:
                for dpi in (400, 600):
                    with self.subTest(font=font, dpi=dpi):
                        observed = observe_header_columns(page, region, 1, dpi)
                        self.assertFalse(all(observed.verified))
                        self.assertTrue(all("raw_text" in c for c in observed.columns))
                        self.assertTrue(
                            any(
                                c.get("detector_conflict") or not c["text"]
                                for c in observed.columns
                            )
                        )
                        self.assertTrue(
                            any(
                                c.get("physical_header_lines") for c in observed.columns
                            )
                        )
