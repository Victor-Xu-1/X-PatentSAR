"""Joined original endpoint/unit rows keep literal scientific identity."""

import copy
import json
import unittest

import fitz

from patent_sar_extractor.core.activity_header_columns import observe_header_columns
from patent_sar_extractor.core.activity_header_identity import detector_header_conflict
from patent_sar_extractor.core.activity_header_metrics import normalize_metric_text
from patent_sar_extractor.core.activity_header_observation import refine_scanned_header
from patent_sar_extractor.core.activity_header_proof import valid_header_proof
from patent_sar_extractor.core.activity_headers import context_from_text, grid_schema


def original_inline_header():
    with fitz.open() as original:
        page = original.new_page(width=360, height=260)
        page.insert_text((50, 55), "Table 9. Binding activity", fontsize=8)
        xs, ys = [50, 75, 120, 170, 225], [75, 112, 130]
        for x in xs:
            page.draw_line((x, ys[0]), (x, ys[-1]), width=0.4)
        for y in ys:
            page.draw_line((xs[0], y), (xs[-1], y), width=0.4)
        headers = (
            ("No.",),
            ("TargetX", "AssayA", "EC50 (nM)"),
            ("TargetX", "AssayA", "DC50 (nM)"),
            ("TargetX", "AssayA", "Dmax (%)"),
        )
        for column, lines in enumerate(headers):
            for row, text in enumerate(lines):
                width = fitz.get_text_length(text, fontname="tiro", fontsize=6.2)
                page.insert_text(
                    ((xs[column] + xs[column + 1] - width) / 2, 84 + row * 9),
                    text,
                    fontname="tiro",
                    fontsize=6.2,
                )
        pixels = page.get_pixmap(
            matrix=fitz.Matrix(240 / 72, 240 / 72), alpha=False
        ).tobytes("png")
    document = fitz.open()
    page = document.new_page(width=360, height=260)
    page.insert_image(page.rect, stream=pixels)
    return document, page, {"xs": xs, "ys": ys}, "\n".join(headers[-1])


class HeaderInlineSourceTests(unittest.TestCase):
    def test_saved_header_keeps_original_wrapper_and_rechecks_known_unit_conflicts(
        self,
    ):
        document, page, region, _expected = original_inline_header()
        schema = grid_schema(
            context_from_text("Table 9. Binding activity"),
            [["No.", "Noise", "Noise", "Noise"]],
        )
        with document:
            observed = refine_scanned_header(page, region, schema)
        proof = json.loads(json.dumps(observed.header_resolution))
        self.assertTrue(valid_header_proof(proof), proof)
        parts = proof["observations"][0]["columns"][-1]["detection_parts"]
        self.assertIn(
            "((%)",
            [part["text"] for part in parts],
            "Raw detector evidence is not rewritten",
        )
        changed = copy.deepcopy(proof)
        changed["observations"][0]["columns"][-1]["detection_parts"][-1]["text"] = (
            "((nM)"
        )
        self.assertFalse(valid_header_proof(changed))

    def test_only_complete_explicit_unit_fragments_share_wrapper_typography(self):
        for raw, unit in (
            ("nM", "nM"),
            ("((nM))", "nM"),
            ("((%)", "%"),
            ("( ( μM ) )", "μM"),
        ):
            with self.subTest(raw=raw):
                self.assertEqual(normalize_metric_text(raw), f"({unit})")
        for raw in ("((nM mutant))", "((%/o))", "Dmax ((%)", "(unknown unit)"):
            with self.subTest(raw=raw):
                self.assertEqual(normalize_metric_text(raw), raw)

    def test_complete_original_rows_are_not_refused_for_a_split_wrapper_detection(self):
        document, page, region, expected = original_inline_header()
        with document:
            for dpi in (400, 600):
                observed = observe_header_columns(page, region, 1, dpi)
                column = observed.columns[-1]
                with self.subTest(dpi=dpi):
                    self.assertEqual(column["raw_text"], expected)
                    self.assertGreaterEqual(column["confidence"], 0.99)
                    self.assertFalse(column["crosses_boundary"])
                    self.assertTrue(observed.verified[-1], column["detection_parts"])

    def test_known_units_endpoints_targets_and_conditions_still_cannot_be_replaced(
        self,
    ):
        fresh = "TargetX AssayA Dmax (%)"
        for original in (
            "TargetX AssayA Dmax ((nM)",
            "TargetX AssayA DC50 (%)",
            "TargetY AssayA Dmax (%)",
            "TargetX AssayB Dmax (%)",
            "TargetX AssayA Dmax (%) at 24 h",
        ):
            with self.subTest(original=original):
                self.assertTrue(
                    detector_header_conflict(
                        [{"text": original, "confidence": 0.99}], fresh
                    )
                )


if __name__ == "__main__":
    unittest.main()
