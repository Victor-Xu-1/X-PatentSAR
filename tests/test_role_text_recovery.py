"""Actual role production and original replay with controlled literal row output."""

import copy
import unittest
from unittest.mock import patch

import fitz

from patent_sar_extractor.core import activity_grid_role_observation as observer
from patent_sar_extractor.core import cell_raster
from patent_sar_extractor.core.activity_grid_role_proof import valid_role_scope
from patent_sar_extractor.core.role_text_sources import role_text_cells
from patent_sar_extractor.core.source_geometry import (
    SourceTokens,
    native_cell_text,
    source_layout,
)
from patent_sar_extractor.core.source_role_observations import (
    RoleObservationBuffer,
    role_failure,
    scope_observations,
    serialize_role_observations,
    validate_role_catalog,
)
from patent_sar_extractor.core.text_ocr.cell_proof import replay_auxiliary_cell
from patent_sar_extractor.core.text_ocr.source_inventory import auxiliary_source_cells
from tests.test_auxiliary_cell_evidence import ControlledAuxiliary


class RoleTextRecoveryTests(unittest.TestCase):
    def source(self, lines=1):
        authored = fitz.open()
        self.addCleanup(authored.close)
        page = authored.new_page(width=510, height=610)
        xs, ys = [20, 100, 300, 490], [50, 76, 570]
        spectral = [f"1H NMR (400 MHz) {7 + row / 100:.2f} ppm" for row in range(lines)]
        matrix = [
            ["Compound No.", "Preparation", "Characterization"],
            ["041B", "Prepared according to Compound 091C", "\n".join(spectral)],
        ]
        for row, values in enumerate(matrix):
            for column, text in enumerate(values):
                for index, line in enumerate(text.splitlines()):
                    page.insert_text(
                        (xs[column] + 3, ys[row] + 12 + 11 * index), line, fontsize=6
                    )
        for x in xs:
            page.draw_line((x, ys[0]), (x, ys[-1]))
        for y in ys:
            page.draw_line((xs[0], y), (xs[-1], y))
        original = source_layout(page)
        scan = fitz.open()
        self.addCleanup(scan.close)
        raster = scan.new_page(width=page.rect.width, height=page.rect.height)
        raster.insert_image(
            raster.rect,
            stream=page.get_pixmap(matrix=fitz.Matrix(3, 3), alpha=False).tobytes(
                "png"
            ),
        )
        layout = source_layout(raster)
        tokens = SourceTokens(
            [
                {**word, "source": "raster", "confidence": 0.99}
                for word in original.native
            ],
            layout,
            layout.raster_bounds,
        )
        return (
            raster,
            {"xs": xs, "ys": ys},
            tokens,
            SourceTokens(original.native, original),
        )

    def observe(self, lines=1, *, enabled=True, unexpected=False, qualified=False):
        page, grid, tokens, original = self.source(lines)
        current = {"text": ""}
        render_original = cell_raster.render_cell_raster
        auxiliary = ControlledAuxiliary()
        observe_original = auxiliary.observe

        def render(source, bounds, dpi, **options):
            current["text"] = native_cell_text(original, bounds)
            auxiliary.texts = tuple(current["text"].splitlines())
            auxiliary.position = 0
            return render_original(source, bounds, dpi, **options)

        def rows(image):
            text = auxiliary.texts[auxiliary.position % len(auxiliary.texts)]
            auxiliary.position += 1
            result = observe_original(image)
            result["text"] = "Unknown data" if unexpected and "ppm" in text else text
            return result

        auxiliary.observe = rows

        def primary(image, *, use_det, use_cls):
            if use_det:
                return [], None
            return [
                [current["text"] if qualified else "weak", 0.99 if qualified else 0.2]
            ], None

        failures = []
        with (
            patch.object(
                observer, "get_ocr_engine", return_value=("rapidocr", primary)
            ),
            patch.object(observer, "render_cell_raster", render),
            patch.object(cell_raster, "render_cell_raster", render),
            patch(
                "patent_sar_extractor.core.text_ocr.source_capture.get_auxiliary_text_runtime",
                return_value=auxiliary if enabled else None,
            ) as runtime,
        ):
            proof = observer.observe_characterization(
                page,
                grid,
                tokens,
                "Table J. Compound characterization",
                evidence_sink=failures,
            )
        return page, grid, proof, failures, auxiliary, runtime

    def test_weak_physical_cells_recover_through_actual_role_producer(self):
        page, _grid, proof, failures, auxiliary, _runtime = self.observe()
        self.assertIsNotNone(proof, failures)
        self.assertEqual(failures, [])
        self.assertEqual(auxiliary.calls, 12)
        region = {"page_no": 1, "bbox": [20, 50, 490, 570], "role_scope": proof}
        self.assertTrue(valid_role_scope(region))
        payload = {"coverage": {"regions": [region]}}
        cells = list(auxiliary_source_cells(role_text_cells(payload)))
        self.assertEqual(len(cells), 6)
        with patch(
            "patent_sar_extractor.core.text_ocr.source_capture.get_auxiliary_text_runtime",
            side_effect=AssertionError("Readback cannot load a model"),
        ):
            self.assertTrue(all(replay_auxiliary_cell(cell, page) for _, cell in cells))
        for version in (None, [], {}, True, 2):
            changed = copy.deepcopy(proof)
            changed["version"] = version
            self.assertFalse(valid_role_scope({**region, "role_scope": changed}))

    def test_long_source_keeps_differing_rows_and_serializable_rejected_observations(
        self,
    ):
        _page, grid, proof, failures, auxiliary, _runtime = self.observe(40)
        self.assertIsNotNone(proof, failures)
        self.assertEqual(auxiliary.calls, 90)
        region = {"bbox": [20, 50, 490, 570], "role_scope": proof}
        self.assertTrue(valid_role_scope(region))
        text = proof["observations"][0]["matrix"][1][2]
        self.assertEqual(len(text.splitlines()), 40)
        self.assertIn("7.00 ppm", text)
        self.assertIn("7.39 ppm", text)
        cells = {
            key: proof[key] for key in ("xs", "ys", "native_hints", "observations")
        }
        diagnostic = role_failure(
            "unqualified_role_observations", grid, proof["prefix"], cells
        )
        scoped = scope_observations([diagnostic], 1, original_pdf_sha256="a" * 64)
        buffer = RoleObservationBuffer()
        buffer.extend(scoped)
        catalog = serialize_role_observations(buffer)
        validate_role_catalog(catalog, original_pdf_sha256="a" * 64)

    def test_unknown_recovered_content_never_grants_a_source_role(self):
        _page, _grid, proof, failures, _auxiliary, _runtime = self.observe(
            unexpected=True
        )
        self.assertIsNone(proof)
        self.assertEqual(
            [item["reason"] for item in failures], ["unresolved_column_roles"]
        )
        self.assertIn(
            "auxiliary_text",
            failures[0]["source_cells"]["observations"][0]["cells"][-1],
        )

    def test_disabled_auxiliary_preserves_failed_primary(self):
        _page, _grid, proof, failures, auxiliary, _runtime = self.observe(enabled=False)
        self.assertIsNone(proof)
        self.assertEqual(auxiliary.calls, 0)
        self.assertEqual(
            failures[0]["source_cells"]["observations"][0]["cells"][-1]["confidence"],
            0.2,
        )

    def test_complete_qualified_primary_is_not_replaced(self):
        _page, _grid, proof, failures, auxiliary, runtime = self.observe(qualified=True)
        self.assertIsNotNone(proof, failures)
        self.assertEqual(auxiliary.calls, 0)
        runtime.assert_not_called()

    def test_diagnostic_carrier_depth_is_not_a_general_nested_object_exemption(self):
        from patent_sar_extractor.core.source_role_observations import _bounded_tree

        nested = "original"
        for _ in range(18):
            nested = {"nested": nested}
        with self.assertRaises(ValueError):
            _bounded_tree({"unrelated": nested}, text_carriers=True)
        carrier = {
            "source_cells": {"observations": [{"cells": [{"auxiliary_text": nested}]}]}
        }
        with self.assertRaises(ValueError):
            _bounded_tree(carrier, text_carriers=True)
