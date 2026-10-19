"""Physical-row discovery is only a locator; final fields need independent proof."""

import copy
import unittest
from contextlib import contextmanager, nullcontext
from unittest.mock import patch

import fitz

from patent_sar_extractor.core.activity_auxiliary_replay import (
    original_activity_source_errors,
)
from patent_sar_extractor.core.activity_header_layout import discover_header_layout
from patent_sar_extractor.core.activity_header_observation import refine_scanned_header
from patent_sar_extractor.core.activity_header_proof import valid_header_proof
from patent_sar_extractor.core.activity_headers import context_from_text, grid_schema
from patent_sar_extractor.core.table_cells import cell_image
from patent_sar_extractor.core.text_ocr.cell_frames import source_rows
from patent_sar_extractor.core.text_ocr.protocol import frame_digest


def weak_primary(image, *, use_det, use_cls):
    return ([], None) if use_det else ([["unreadable", 0.2]], None)


class PixelOracle:
    """Explicit synthetic pixel/text oracle, not model accuracy evidence."""

    def __init__(self, page, region, matrix):
        self.values, self.calls = {}, 0
        for dpi in (400, 600):
            for start in range(len(matrix)):
                for stop in range(start + 1, min(len(matrix), start + 3) + 1):
                    for c in range(len(matrix[0])):
                        bounds = [
                            region["xs"][c],
                            region["ys"][start],
                            region["xs"][c + 1],
                            region["ys"][stop],
                        ]
                        frame = source_rows(cell_image(page, bounds, dpi), dpi)
                        texts = [row[c] for row in matrix[start:stop] if row[c]]
                        if texts:
                            assert frame is not None and len(frame["images"]) == len(
                                texts
                            )
                            for image, text in zip(frame["images"], texts):
                                digest = frame_digest(image)
                                assert self.values.get(digest, text) == text
                                self.values[digest] = text

    def observe(self, image):
        self.calls += 1
        digest = frame_digest(image)
        return {
            "id": f"{self.calls:032x}",
            "status": "observed",
            "image_sha256": "a" * 64,
            "pixel_sha256": digest,
            "model_fingerprint": "b" * 64,
            "text": self.values[digest],
            "confidence": 0.999,
            "confidence_kind": "uncalibrated_model",
            "device": "cpu",
            "peak_rss_mb": 512.0,
            "cache_hit": False,
        }


class AuxiliaryHeaderDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.matrix = [["Compound", "IC50 (nM)"], ["42", "0.125"], ["42A", "1.8"]]
        self.region = {"xs": [30, 140, 295], "ys": [90, 130, 170, 210]}
        self.document = fitz.open()
        self.addCleanup(self.document.close)
        with fitz.open() as source:
            page = source.new_page(width=340, height=260)
            page.insert_text((30, 65), "Table 3. Binding assay", fontsize=10)
            for r, row in enumerate(self.matrix):
                for c, text in enumerate(row):
                    page.insert_text(
                        (self.region["xs"][c] + 8, self.region["ys"][r] + 24),
                        text,
                        fontsize=10,
                        fontname="hebo",
                    )
            pixels = page.get_pixmap(matrix=fitz.Matrix(3, 3), alpha=False)
            self.page = self.document.new_page(width=340, height=260)
            self.page.insert_image(self.page.rect, stream=pixels.tobytes("png"))
        self.reader = PixelOracle(self.page, self.region, self.matrix)

    def split_unit_header(self):
        """Blank ID continuation is source geometry, not an invented identifier."""
        self.matrix = [["Compound", "IC50"], ["", "(nM)"], ["42", "0.125"]]
        with fitz.open() as source:
            page = source.new_page(width=340, height=260)
            for r, row in enumerate(self.matrix):
                for c, text in enumerate(row):
                    if text:
                        page.insert_text(
                            (self.region["xs"][c] + 8, self.region["ys"][r] + 24),
                            text,
                            fontsize=10,
                            fontname="hebo",
                        )
            pixels = page.get_pixmap(matrix=fitz.Matrix(3, 3), alpha=False)
            document = fitz.open()
            self.addCleanup(document.close)
            self.document = document
            self.page = document.new_page(width=340, height=260)
            self.page.insert_image(self.page.rect, stream=pixels.tobytes("png"))
            self.reader = PixelOracle(self.page, self.region, self.matrix)

    @contextmanager
    def observations(self, reader=None):
        with (
            patch(
                "patent_sar_extractor.core.activity_header_layout.ocr_tokens_with_positions",
                return_value=[],
            ),
            patch(
                "patent_sar_extractor.core.activity_header_layout.table_matrix",
                return_value=[["unreadable", "unreadable"]] * 3,
            ),
            patch(
                "patent_sar_extractor.core.activity_header_layout._prefix",
                return_value="Table 3. Binding assay",
            ),
            patch(
                "patent_sar_extractor.core.activity_header_columns.get_ocr_engine",
                return_value=("rapidocr", weak_primary),
            ),
            patch(
                "patent_sar_extractor.core.text_ocr.configuration.get_auxiliary_text_runtime",
                return_value=reader,
            ),
            patch(
                "patent_sar_extractor.core.activity_header_pair.get_auxiliary_text_runtime",
                return_value=reader,
            ),
            patch(
                "patent_sar_extractor.core.activity_header_observation.ocr_tokens_with_positions",
                return_value=[],
            ),
            patch(
                "patent_sar_extractor.core.activity_header_observation._prefix",
                return_value="Table 3. Binding assay",
            ),
        ):
            yield

    def test_missing_initial_header_can_be_located_from_complete_physical_rows(self):
        with self.observations(self.reader):
            layout = discover_header_layout(
                self.page, self.region, (0, 20, 340, 210), 3
            )
        self.assertIsNotNone(layout.schema)
        self.assertEqual(layout.schema.first_data_row, 1)
        self.assertEqual(layout.schema.raw_headers, ("Compound", "IC50 (nM)"))
        self.assertGreater(self.reader.calls, 0)
        self.assertEqual(
            [o["method"] for o in layout.observations[:2]],
            ["header_layout_400dpi", "header_layout_600dpi"],
        )

    def test_unconfigured_auxiliary_does_not_start_physical_row_recovery(self):
        with self.observations():
            layout = discover_header_layout(
                self.page, self.region, (0, 20, 340, 210), 3
            )
        self.assertIsNone(layout.schema)
        self.assertEqual(self.reader.calls, 0)

    def test_split_unit_and_blank_identifier_cell_do_not_swallow_first_value_row(self):
        self.split_unit_header()
        with self.observations(self.reader):
            layout = discover_header_layout(
                self.page, self.region, (0, 20, 340, 210), 3
            )
        self.assertIsNotNone(layout.schema)
        self.assertEqual(layout.schema.first_data_row, 2)
        self.assertEqual(layout.schema.raw_headers, ("Compound", "IC50\n(nM)"))
        self.assertNotIn("0.125", str(layout.schema.groups))

    def test_final_header_still_needs_independent_column_and_source_proof(self):
        with self.observations(self.reader):
            result = refine_scanned_header(self.page, self.region, None)
        self.assertIsNotNone(result)
        self.assertEqual(
            result.header_resolution["status"], "observed_header_consensus"
        )
        self.assertEqual(len(result.header_resolution["observations"]), 2)

    def test_unknown_unit_boundary_can_expand_only_from_qualified_original_rows(self):
        self.split_unit_header()
        old = grid_schema(
            context_from_text("Table 3. Binding assay"), [["Compound", "IC50"]]
        )
        with self.observations(self.reader):
            result = refine_scanned_header(self.page, self.region, old)
        self.assertIsNotNone(result)
        self.assertEqual(result.first_data_row, 2)
        self.assertEqual(result.raw_headers, ("Compound", "IC50\n(nM)"))
        self.assertTrue(valid_header_proof(result.header_resolution))
        proof = {**result.header_resolution, "page_no": 1}
        payload = {"header_observations": {"controlled": proof}}
        self.assertEqual(
            original_activity_source_errors(
                payload, open_original=lambda: nullcontext(self.document)
            ),
            [],
        )
        # Source pixels in a blank continuation cannot be replaced by a success flag.
        self.page.insert_text((45, 151), "interference", fontsize=8)
        self.assertTrue(
            original_activity_source_errors(
                payload, open_original=lambda: nullcontext(self.document)
            )
        )

    def test_missing_identifier_role_is_not_filled_from_column_position(self):
        self.reader.values = {
            k: ("Noise" if value == "Compound" else value)
            for k, value in self.reader.values.items()
        }
        with self.observations(self.reader):
            layout = discover_header_layout(
                self.page, self.region, (0, 20, 340, 210), 3
            )
        self.assertIsNone(layout.schema)
        self.assertEqual(len(layout.observations), 4)

    def test_known_endpoint_unit_cannot_be_outvoted_by_a_high_scoring_model(self):
        sink = []
        with (
            self.observations(self.reader),
            patch(
                "patent_sar_extractor.core.activity_header_layout.table_matrix",
                return_value=[["Compound", "IC50 (uM)"]],
            ),
        ):
            result = refine_scanned_header(
                self.page, self.region, None, evidence_sink=sink
            )
        self.assertIsNone(result)
        self.assertEqual(sink[0]["status"], "unresolved")
        self.assertIn(1, sink[0]["conflicting_columns"])

    def test_changed_locator_or_removed_auxiliary_proof_cannot_retain_saved_success(
        self,
    ):
        with self.observations(self.reader):
            result = refine_scanned_header(self.page, self.region, None)
        for mutation in ("matrix", "bounds", "auxiliary", "primary_frame"):
            proof = copy.deepcopy(result.header_resolution)
            view = proof["discovery_observations"][2]
            if mutation == "matrix":
                view["matrix"][0][1] = "EC50 (nM)"
            elif mutation == "bounds":
                view["rows"][0]["bbox"][0] += 1
            elif mutation == "auxiliary":
                del view["rows"][0]["columns"][1]["auxiliary_text"]
            else:
                view["rows"][0]["columns"][1]["source_frame"]["pixel_sha256"] = "c" * 64
            self.assertFalse(valid_header_proof(proof), mutation)
