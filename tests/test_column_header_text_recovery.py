"""Original generated scan headers through real cell capture and controlled OCR replies."""

import copy
import unittest
from unittest.mock import patch

import fitz

from patent_sar_extractor.core import activity_grid_role_observation as observer
from patent_sar_extractor.core import cell_raster
from patent_sar_extractor.core.logical_column_partitions import nominate_unruled_headers
from patent_sar_extractor.core.ruled_structure_headers import (
    observe_ruled_header,
    ruled_header_roles,
)
from patent_sar_extractor.core.source_geometry import (
    SourceTokens,
    native_cell_text,
    source_layout,
)
from patent_sar_extractor.core.unruled_structure_headers import (
    observe_unruled_header,
    unruled_header_roles,
)
from tests.test_auxiliary_cell_evidence import ControlledAuxiliary


class ColumnHeaderTextRecoveryTests(unittest.TestCase):
    def source(self, *, ruled=True, native=False):
        original = fitz.open()
        self.addCleanup(original.close)
        page = original.new_page(width=500, height=260)
        page.insert_text((25, 30), "Table J. Compound structures", fontsize=8)
        page.insert_text((25, 63), "Compound No.", fontsize=9)
        page.insert_text((185, 63), "Structure", fontsize=9)
        grid = {"xs": [20, 160, 480], "ys": [40, 78, 200]}
        if ruled:
            for x in grid["xs"]:
                page.draw_line((x, 40), (x, 200))
            for y in grid["ys"]:
                page.draw_line((20, y), (480, y))
        layout = source_layout(page)
        reference = SourceTokens(layout.native, layout)
        if native:
            return page, grid, reference, reference
        scan = fitz.open()
        self.addCleanup(scan.close)
        raster = scan.new_page(width=500, height=260)
        raster.insert_image(
            raster.rect,
            stream=page.get_pixmap(matrix=fitz.Matrix(3, 3), alpha=False).tobytes(
                "png"
            ),
        )
        layout = source_layout(raster)
        tokens = SourceTokens(
            [
                {
                    **{
                        key: value
                        for key, value in word.items()
                        if key != "native_paint"
                    },
                    "source": "raster",
                    "confidence": 0.99,
                }
                for word in reference
            ],
            layout,
            layout.raster_bounds,
        )
        return raster, grid, tokens, reference

    def observe(
        self,
        *,
        ruled=True,
        enabled=True,
        qualified=False,
        native=False,
        conflict=False,
        wrong=False,
        weak_auxiliary=False,
    ):
        page, grid, tokens, reference = self.source(ruled=ruled, native=native)
        current = {"text": "", "dpi": 0}
        auxiliary = ControlledAuxiliary()
        original_render, original_observe = (
            cell_raster.render_cell_raster,
            auxiliary.observe,
        )

        def render(source, bounds, dpi, **kwargs):
            current.update(text=native_cell_text(reference, bounds), dpi=dpi)
            return original_render(source, bounds, dpi, **kwargs)

        def rows(image):
            result = original_observe(image)
            result["text"] = "Intermediate" if wrong else current["text"]
            if weak_auxiliary:
                result["confidence"] = 0.95
            return result

        auxiliary.observe = rows

        def primary(image, *, use_det, use_cls):
            if use_det:
                return [], None
            known = qualified or conflict and current["dpi"] == 400
            text = "Other known column" if conflict and known else current["text"]
            return [[text if known else "weak", 0.99 if known else 0.2]], None

        with (
            patch.object(
                observer, "get_ocr_engine", return_value=("rapidocr", primary)
            ) as main,
            patch.object(observer, "render_cell_raster", render),
            patch.object(cell_raster, "render_cell_raster", render),
            patch(
                "patent_sar_extractor.core.text_ocr.source_capture.get_auxiliary_text_runtime",
                return_value=auxiliary if enabled else None,
            ) as runtime,
        ):
            if ruled:
                scope = observe_ruled_header(page, tokens, grid, "a" * 64)
                roles = ruled_header_roles(scope)
            else:
                nominations = nominate_unruled_headers(tokens, [500, 260])
                self.assertEqual(len(nominations), 1)
                scope = observe_unruled_header(page, tokens, nominations[0], "a" * 64)
                roles = unruled_header_roles(scope)
        return page, scope, roles, auxiliary, runtime, main

    def test_weak_ruled_columns_use_the_existing_paired_recovery(self):
        _page, scope, roles, auxiliary, _runtime, _main = self.observe()
        self.assertIsNotNone(roles)
        self.assertEqual(roles["pairs"], ((0, 1),))
        self.assertEqual(auxiliary.calls, 4)
        cells = scope["role_cells"]["observations"]
        self.assertEqual(cells[0]["matrix"], [["Compound No.", "Structure"]])

    def test_weak_unruled_columns_use_the_same_recovery_without_printed_rules(self):
        _page, _scope, roles, auxiliary, _runtime, _main = self.observe(ruled=False)
        self.assertIsNotNone(roles)
        self.assertEqual(roles["pairs"], ((0, 1),))
        self.assertEqual(auxiliary.calls, 4)

    def test_disabled_recovery_remains_unresolved(self):
        _page, _scope, roles, auxiliary, runtime, _main = self.observe(enabled=False)
        self.assertIsNone(roles)
        self.assertEqual(auxiliary.calls, 0)
        self.assertEqual(runtime.call_count, 2)

    def test_complete_primary_does_not_load_an_auxiliary_runtime(self):
        _page, _scope, roles, auxiliary, runtime, _main = self.observe(qualified=True)
        self.assertIsNotNone(roles)
        self.assertEqual(auxiliary.calls, 0)
        runtime.assert_not_called()

    def test_native_headers_do_not_call_any_optical_recognizer(self):
        _page, _scope, roles, auxiliary, runtime, main = self.observe(native=True)
        self.assertIsNotNone(roles)
        self.assertEqual(auxiliary.calls, 0)
        runtime.assert_not_called()
        main.assert_not_called()

    def test_known_primary_conflicts_are_not_overwritten(self):
        _page, scope, roles, auxiliary, _runtime, _main = self.observe(conflict=True)
        self.assertIsNone(roles)
        self.assertGreater(auxiliary.calls, 0)
        self.assertEqual(
            scope["role_cells"]["observations"][0]["cells"][0]["text"],
            "Other known column",
        )

    def test_wrong_auxiliary_role_and_low_scores_do_not_get_promoted(self):
        for options in ({"wrong": True}, {"weak_auxiliary": True}):
            with self.subTest(options=options):
                _page, _scope, roles, auxiliary, _runtime, _main = self.observe(
                    **options
                )
                self.assertIsNone(roles)
                self.assertGreater(auxiliary.calls, 0)

    def test_source_replay_cannot_be_loaded_from_a_model_or_saved_flag(self):
        from patent_sar_extractor.core.text_ocr.cell_proof import replay_auxiliary_cell

        _page, scope, roles, _auxiliary, _runtime, _main = self.observe()
        self.assertIsNotNone(roles)
        with patch(
            "patent_sar_extractor.core.text_ocr.source_capture.get_auxiliary_text_runtime",
            side_effect=AssertionError("No OCR on replay"),
        ):
            for view in scope["role_cells"]["observations"]:
                for cell in view["cells"]:
                    self.assertTrue(replay_auxiliary_cell(cell, _page))
        changed = copy.deepcopy(scope)
        changed["role_cells"]["observations"][0]["cells"][0]["text"] = "Example"
        with self.assertRaisesRegex(ValueError, "clipping scope"):
            ruled_header_roles(changed)

    def test_carried_headers_replay_on_the_original_page_and_deduplicate(self):
        from patent_sar_extractor.core.binding_original_replay import (
            original_binding_source_errors,
        )
        from patent_sar_extractor.core.role_text_sources import role_text_cells

        page, scope, roles, _auxiliary, _runtime, _main = self.observe()
        self.assertIsNotNone(roles)
        payload = {
            "source_sections": [
                {
                    "role": "structure_column_anchor",
                    "page_no": 1,
                    "source": {"header_scope": scope},
                },
                {
                    "role": "structure_column_anchor",
                    "page_no": 2,
                    "source": {
                        "header_scope": {
                            "kind": "continued_ruled_columns",
                            "anchor_scope": copy.deepcopy(scope),
                        }
                    },
                },
            ]
        }
        sources = tuple(role_text_cells(payload))
        self.assertEqual(len(sources), 2)
        self.assertEqual({number for number, _cell in sources}, {1})
        with patch(
            "patent_sar_extractor.core.text_ocr.source_capture.get_auxiliary_text_runtime",
            side_effect=AssertionError("No model on original replay"),
        ):
            self.assertEqual(
                original_binding_source_errors(page.parent, [], role_text=sources), []
            )
            page.draw_rect(fitz.Rect(25, 52, 70, 68), fill=(0, 0, 0))
            self.assertTrue(
                original_binding_source_errors(page.parent, [], role_text=sources)
            )

    def test_ordinary_and_native_headers_share_the_existing_source_inventory(self):
        from patent_sar_extractor.core.role_original_replay import (
            original_role_source_errors,
        )
        from patent_sar_extractor.core.role_text_sources import role_text_cells

        for native in (False, True):
            with self.subTest(native=native):
                page, scope, roles, _auxiliary, _runtime, _main = self.observe(
                    qualified=True, native=native
                )
                self.assertIsNotNone(roles)
                sources = tuple(
                    role_text_cells(
                        {
                            "source_sections": [
                                {
                                    "role": "structure_column_anchor",
                                    "page_no": 1,
                                    "source": {"header_scope": scope},
                                }
                            ]
                        }
                    )
                )
                self.assertEqual(len(sources), 2 if native else 4)
                self.assertEqual(original_role_source_errors(page.parent, sources), [])

    def test_header_recovery_keeps_eight_row_twelve_point_authority(self):
        from patent_sar_extractor.core.text_ocr.source_capture import refine_source_text

        with patch(
            "patent_sar_extractor.core.role_text_capture.refine_source_text",
            wraps=refine_source_text,
        ) as refine:
            _page, _scope, roles, _auxiliary, _runtime, _main = self.observe()
        self.assertIsNotNone(roles)
        self.assertEqual(refine.call_count, 2)
        for call in refine.call_args_list:
            self.assertEqual(
                call.kwargs,
                {"maximum_rows": 8, "maximum_row_height": 12, "allow_chunks": False},
            )
