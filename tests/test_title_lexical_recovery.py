"""Generated titles: confidence is not agreement; original claims stay retained."""

import copy
import json
import unittest
from unittest.mock import patch

import fitz

from patent_sar_extractor.core.source_geometry import SourceTokens, source_layout
from patent_sar_extractor.core.source_observations import source_cell_observation
from patent_sar_extractor.core.source_paint_visibility import native_paint_view
from patent_sar_extractor.core.title_original_replay import replay_source_title
from patent_sar_extractor.core.title_source_capture import observe_source_title
from patent_sar_extractor.core.title_source_proof import source_title_text
from tests.test_auxiliary_cell_evidence import ControlledAuxiliary


class TitleLexicalRecoveryTests(unittest.TestCase):
    def original(self, text):
        with fitz.open() as lettering:
            initial = lettering.new_page(width=430, height=200)
            initial.insert_text((50, 70), text, fontsize=10)
            layout = source_layout(initial)
            hints = [
                {key: value for key, value in token.items() if key != "native_paint"}
                | {"source": "raster", "confidence": 0.99}
                for token in layout.native
            ]
            image = initial.get_pixmap(matrix=fitz.Matrix(3, 3), alpha=False)
        document = fitz.open()
        self.addCleanup(document.close)
        page = document.new_page(width=430, height=200)
        page.insert_image(page.rect, stream=image.tobytes("png"))
        layout = source_layout(page)
        tokens = SourceTokens(hints, layout, tuple(page.rect))
        raw = source_cell_observation(tokens, [40, 50, 400, 80], native=False)
        self.assertEqual(raw["status"], "qualified")
        return page, layout, raw

    def capture(self, *, title="Table 63. Compounds Table", other=None, auxiliary=None):
        page, layout, raw = self.original(title)
        values = iter((title, other or title))

        def primary(_image, *, use_det, use_cls):
            self.assertFalse(use_cls)
            return ([], None) if use_det else ([[next(values), 0.99]], None)

        reader = auxiliary or ControlledAuxiliary((title,))
        with (
            patch(
                "patent_sar_extractor.core.page_ocr_cache.get_ocr_engine",
                return_value=("rapidocr", primary),
            ),
            patch(
                "patent_sar_extractor.core.text_ocr.configuration.get_auxiliary_text_runtime",
                return_value=reader,
            ),
        ):
            proof = observe_source_title(
                page, raw, layout=layout, paint_view=native_paint_view(page)
            )
        return page, proof, reader

    def test_unknown_role_word_uses_complete_independent_views_without_editing_primaries(
        self,
    ):
        page, proof, reader = self.capture(other="Table 63. Componds Table")
        self.assertEqual(source_title_text(proof), "Table 63. Compounds Table")
        self.assertEqual(reader.calls, 2)
        self.assertEqual(
            [reading["raw_text"] for reading in proof["observations"]],
            ["Table 63. Compounds Table", "Table 63. Componds Table"],
        )
        saved = json.loads(json.dumps(proof))
        self.assertEqual(source_title_text(saved), "Table 63. Compounds Table")
        replay_source_title(page, saved)

    def test_agreed_complete_primary_does_not_acquire_auxiliary(self):
        _page, proof, reader = self.capture()
        self.assertEqual(source_title_text(proof), "Table 63. Compounds Table")
        self.assertEqual(reader.calls, 0)

    def test_known_role_or_table_identity_conflicts_never_start_auxiliary_voting(self):
        for other in (
            "Table 63. Intermediate Compounds",
            "Table 64. Compounds Table",
            "Table 63. Control Compounds",
            "Table 63. Not Compounds",
            "Table 63. Compounds and Intermediates",
        ):
            with self.subTest(other=other):
                _page, proof, reader = self.capture(other=other)
                self.assertIsNone(source_title_text(proof))
                self.assertEqual(reader.calls, 0)

    def test_model_disagreement_or_changed_literal_cannot_choose_a_title(self):
        for outputs in (
            ("Table 63. Compounds Table", "Table 63. Intermediates Table"),
            ("Table 64. Compounds Table",),
            ("Table 63. Intermediate Compounds",),
        ):
            with self.subTest(outputs=outputs):
                _page, proof, reader = self.capture(
                    other="Table 63. Componds Table",
                    auxiliary=ControlledAuxiliary(outputs),
                )
                self.assertIsNone(source_title_text(proof))
                self.assertGreater(reader.calls, 0)

    def test_changed_original_pixels_or_retained_primary_never_replay(self):
        page, proof, _reader = self.capture(other="Table 63. Componds Table")
        self.assertIsNotNone(source_title_text(proof))
        changed = copy.deepcopy(proof)
        changed["observations"][1]["raw_text"] = "Table 64. Componds Table"
        self.assertIsNone(source_title_text(changed))
        page.draw_rect(fitz.Rect(70, 62, 73, 65), fill=(0, 0, 0), width=0)
        with self.assertRaises(ValueError):
            replay_source_title(page, proof)

    def test_title_permission_cannot_be_reused_for_generic_measurements(self):
        from patent_sar_extractor.core.text_ocr.cell_proof import effective_cells

        _page, proof, _reader = self.capture(other="Table 63. Componds Table")
        with self.assertRaises(ValueError):
            effective_cells(proof["auxiliary_title"])

    def test_missing_model_row_changed_frame_and_model_are_not_saved_success(self):
        _page, baseline, _reader = self.capture(other="Table 63. Componds Table")
        for mutation in (
            "row",
            "model",
            "primary",
            "frame",
            "marker",
            "scope",
            "attempts",
            "native_window",
            "raster_scope",
        ):
            with self.subTest(mutation=mutation):
                proof = copy.deepcopy(baseline)
                packet = proof["auxiliary_title"]
                if mutation == "row":
                    packet["views"][0]["requests"].clear()
                elif mutation == "model":
                    packet["model"]["fingerprint"] = "0" * 64
                elif mutation == "primary":
                    packet["views"][0]["primary"]["raw_text"] = (
                        "Table 64. Compounds Table"
                    )
                elif mutation == "frame":
                    packet["views"][0]["frame"]["pixel_sha256"] = "0" * 64
                elif mutation == "marker":
                    del proof["auxiliary_title"]
                elif mutation == "scope":
                    packet["maximum_row_height"] = 12
                elif mutation == "native_window":
                    proof["native_window"] = {}
                elif mutation == "raster_scope":
                    proof["raster_bounds"] = [-1, -1, 999, 999]
                else:
                    proof["auxiliary_title_attempts"] = "success"
                self.assertIsNone(source_title_text(proof))

    def test_same_request_identity_cannot_hide_two_source_observations(self):
        from patent_sar_extractor.core.text_ocr.source_inventory import (
            auxiliary_source_cells,
        )

        _page, first, _reader = self.capture(other="Table 63. Componds Table")
        _page, second, _reader = self.capture(
            title="Table 27. Examples Table",
            other="Table 27. Exmples Table",
        )
        carrier = {"method": "original_title", "title_source": first}
        self.assertEqual(
            list(auxiliary_source_cells([(1, carrier), (1, carrier)])), [(1, carrier)]
        )
        with self.assertRaisesRegex(ValueError, "conflicting outputs"):
            list(
                auxiliary_source_cells(
                    [
                        (1, carrier),
                        (1, {"method": "original_title", "title_source": second}),
                    ]
                )
            )

    def test_worker_original_source_replay_and_read_side_runtime_are_separate(self):
        from patent_sar_extractor.core.binding_auxiliary_replay import (
            has_binding_auxiliary,
            original_binding_auxiliary_errors,
        )
        from patent_sar_extractor.core.role_original_replay import (
            original_role_source_errors,
        )

        page, proof, _reader = self.capture(other="Table 63. Componds Table")
        carrier = [(1, {"method": "original_title", "title_source": proof})]
        with patch(
            "patent_sar_extractor.core.text_ocr.configuration.get_auxiliary_text_runtime",
            side_effect=AssertionError("Read side must never acquire an OCR runtime"),
        ):
            self.assertTrue(has_binding_auxiliary([], role_text=carrier))
            self.assertEqual(original_role_source_errors(page.parent, carrier), [])
            self.assertEqual(
                original_binding_auxiliary_errors(page.parent, [], role_text=carrier),
                [],
            )
            page.draw_rect(fitz.Rect(70, 62, 73, 65), fill=(0, 0, 0), width=0)
            self.assertTrue(
                original_binding_auxiliary_errors(page.parent, [], role_text=carrier)
            )

    def test_measurement_prose_and_other_known_words_cannot_gain_title_permission(self):
        for title, other in (
            ("Table 63. Compounds DC50 nM", "Table 63. Componds DC50 nM"),
            ("Table 63. Selected Compounds", "Table 63. Slected Compounds"),
            ("Table 63. Compounds Table", "Table 63. Compounds Tble"),
            ("Table 063. Compounds Table", "Table 63. Componds Table"),
        ):
            with self.subTest(title=title, other=other):
                _page, proof, reader = self.capture(title=title, other=other)
                self.assertIsNone(source_title_text(proof))
                self.assertEqual(reader.calls, 0)

    def test_recovered_original_title_drives_the_same_cross_page_catalogue_binder(self):
        from patent_sar_extractor.core.caption_binding_proof import (
            valid_caption_binding_evidence,
        )
        from patent_sar_extractor.core.caption_grid_binding import bind_caption_grids
        from tests.test_caption_role_continuation import binding, two_pages

        for title, uncertain, role in (
            ("Table 31. Compounds", "Table 31. Componds", "compound"),
            ("Table 31. Intermediates", "Table 31. Intermedates", "nonfinal"),
        ):
            with self.subTest(role=role):
                document, structures, boxes, grids, pages = two_pages(first_title="")
                self.addCleanup(document.close)
                with fitz.open() as lettering:
                    source = lettering.new_page()
                    source.insert_text((50, 85), title, fontsize=10)
                    initial = source_layout(source)
                    hints = [
                        {
                            key: value
                            for key, value in token.items()
                            if key != "native_paint"
                        }
                        | {"source": "raster", "confidence": 0.99}
                        for token in initial.native
                    ]
                    bounds = fitz.Rect(40, 65, 400, 90)
                    image = source.get_pixmap(
                        clip=bounds, matrix=fitz.Matrix(3, 3), alpha=False
                    )
                document[0].insert_image(bounds, stream=image.tobytes("png"))

                def tokens_for_page(page, hints=hints):
                    layout = source_layout(page)
                    return SourceTokens(
                        [*layout.native, *(hints if page.number == 0 else [])],
                        layout,
                        layout.raster_bounds,
                    )

                values = iter((title, uncertain))

                def primary(_image, *, use_det, use_cls, values=values):
                    return ([], None) if use_det else ([[next(values), 0.99]], None)

                reader = ControlledAuxiliary((title,))
                with (
                    patch(
                        "patent_sar_extractor.core.page_ocr_cache.get_ocr_engine",
                        return_value=("rapidocr", primary),
                    ),
                    patch(
                        "patent_sar_extractor.core.text_ocr.configuration.get_auxiliary_text_runtime",
                        return_value=reader,
                    ),
                ):
                    result = bind_caption_grids(
                        document,
                        structures,
                        boxes,
                        pages,
                        grids_for_page=lambda page, observed=grids: observed[
                            page.number + 1
                        ],
                        tokens_for_page=tokens_for_page,
                    )
                self.assertEqual(reader.calls, 2)
                self.assertEqual(result.issues, [])
                if role == "compound":
                    self.assertEqual(
                        [pair["label"] for pair in result.bindings],
                        ["41A", "89B", "73C", "104D"],
                    )
                    for pair in result.bindings:
                        self.assertTrue(
                            valid_caption_binding_evidence(
                                json.loads(json.dumps(binding(pair)))
                            )
                        )
                else:
                    self.assertEqual(result.bindings, [])
                    self.assertEqual(len(result.exclusions), 2)

    def test_call_local_reuse_preserves_both_success_and_failed_attempts(self):
        from patent_sar_extractor.core.title_source_reuse import (
            remember_title_observation,
        )

        for output, expected in (
            ("Table 63. Compounds Table", "Table 63. Compounds Table"),
            ("Table 64. Compounds Table", None),
        ):
            with self.subTest(output=output):
                page, proof, _reader = self.capture(
                    other="Table 63. Componds Table",
                    auxiliary=ControlledAuxiliary((output,)),
                )
                cache = {}
                remember_title_observation(proof, cache)
                self.assertEqual(len(cache), 1)
                with (
                    patch(
                        "patent_sar_extractor.core.page_ocr_cache.get_ocr_engine",
                        side_effect=AssertionError("No repeated primary read"),
                    ),
                    patch(
                        "patent_sar_extractor.core.text_ocr.configuration.get_auxiliary_text_runtime",
                        side_effect=AssertionError("No repeated auxiliary read"),
                    ),
                ):
                    replayed = observe_source_title(
                        page,
                        proof["nomination_source"],
                        layout=source_layout(page),
                        paint_view=native_paint_view(page),
                        title_cache=cache,
                    )
                self.assertEqual(source_title_text(replayed), expected)
                self.assertEqual(
                    replayed["auxiliary_title_attempts"],
                    proof["auxiliary_title_attempts"],
                )
                self.assertEqual(replayed["observations"], proof["observations"])
                self.assertIsNot(replayed["observations"], proof["observations"])
