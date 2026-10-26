"""Catalogue roles must read every original title word, including outlined ink."""

import copy
import json
import unittest
from unittest.mock import patch

import fitz

from patent_sar_extractor.core.caption_grid_binding import bind_caption_grids
from patent_sar_extractor.core.caption_role_observation import observe_caption_role
from patent_sar_extractor.core.caption_role_proof import caption_role_status
from patent_sar_extractor.core.source_geometry import SourceTokens, source_layout
from patent_sar_extractor.core.table_geometry import detect_ruled_table_regions
from patent_sar_extractor.core.title_original_replay import replay_source_title
from patent_sar_extractor.core.title_source_proof import source_title_text
from tests.test_caption_source_roles import catalog


def original_catalogue(
    *, outlined="Intermediate", tail="Compounds", fully_outlined=False
):
    document, structures, boxes = catalog(None, prefixed=True)
    page = document[0]
    if fully_outlined:
        with fitz.open() as lettering:
            source = lettering.new_page(width=page.rect.width, height=page.rect.height)
            source.insert_text(
                (50, 85), "Table 47. Intermediate Compounds", fontsize=10
            )
            with (
                fitz.open(
                    stream=source.get_svg_image(text_as_path=True).encode(),
                    filetype="svg",
                ) as image,
                fitz.open(stream=image.convert_to_pdf(), filetype="pdf") as paths,
            ):
                page.show_pdf_page(page.rect, paths, 0)
        return document, structures, boxes
    page.insert_text((50, 85), "Table 47.", fontsize=10)
    if outlined:
        with fitz.open() as lettering:
            source = lettering.new_page(width=page.rect.width, height=page.rect.height)
            source.insert_text((100, 85), outlined, fontsize=10)
            svg = source.get_svg_image(text_as_path=True).encode()
            with (
                fitz.open(stream=svg, filetype="svg") as image,
                fitz.open(stream=image.convert_to_pdf(), filetype="pdf") as paths,
            ):
                assert not paths[0].get_text().strip()
                page.show_pdf_page(page.rect, paths, 0)
        left = 100 + fitz.get_text_length(outlined + " ", fontsize=10)
    else:
        left = 100
    page.insert_text((left, 85), tail, fontsize=10)
    return document, structures, boxes


class CatalogueTitleSourceTests(unittest.TestCase):
    def setUp(self):
        self.factory = self.enterContext(
            patch(
                "patent_sar_extractor.core.page_ocr_cache._build_ocr_engine",
                side_effect=AssertionError("No native OCR in generated source checks"),
            )
        )
        self.enterContext(
            patch(
                "patent_sar_extractor.core.text_ocr.source_capture.get_auxiliary_text_runtime",
                return_value=None,
            )
        )

    def tearDown(self):
        self.assertEqual(self.factory.call_count, 0)

    @staticmethod
    def engine(literal):
        def controlled(image, *, use_det, use_cls):
            return ([], None) if use_det else ([[literal, 0.99]], None)

        return controlled

    def bind(self, *, reading=None, **options):
        document, structures, boxes = original_catalogue(**options)
        with (
            document,
            patch(
                "patent_sar_extractor.core.page_ocr_cache.get_ocr_engine",
                return_value=("rapidocr", self.engine(reading))
                if reading is not None
                else None,
            ),
        ):
            return bind_caption_grids(document, structures, boxes, [1])

    def test_native_title_keeps_fast_path_without_extra_ocr(self):
        result = self.bind(outlined="")
        self.assertEqual(
            [pair["label"] for pair in result.bindings], ["I-004A", "I-009B"]
        )
        self.assertEqual(result.issues, [])

    def test_unread_outlined_nonfinal_word_is_not_a_final_catalogue(self):
        result = self.bind()
        self.assertEqual(len(result.bindings), 0)
        self.assertEqual(result.exclusions, [])
        self.assertTrue(result.issues)

    def test_fully_outlined_title_is_not_an_implicit_final_catalogue(self):
        result = self.bind(fully_outlined=True)
        self.assertEqual(len(result.bindings), 0)
        self.assertEqual(len(result.exclusions), 0)
        self.assertTrue(result.issues)

    def test_complete_context_recovers_a_title_missing_from_both_word_locators(self):
        result = self.bind(
            fully_outlined=True, reading="Table 47. Intermediate Compounds"
        )
        self.assertEqual(len(result.bindings), 0)
        self.assertEqual(len(result.exclusions), 1)

    def test_complete_original_read_excludes_the_numbered_intermediates(self):
        result = self.bind(reading="Table 47. Intermediate Compounds")
        self.assertEqual(len(result.bindings), 0)
        self.assertEqual(len(result.exclusions), 1)

    def test_repeated_native_subset_cannot_certify_unread_role_ink(self):
        result = self.bind(reading="Table 47. Compounds")
        self.assertEqual(len(result.bindings), 0)
        self.assertEqual(result.exclusions, [])
        self.assertTrue(result.issues)

    def test_mixed_title_cannot_publish_or_silently_exclude_a_catalogue(self):
        result = self.bind(
            outlined="Compounds and",
            tail="intermediates",
            reading="Table 47. Compounds and intermediates",
        )
        self.assertEqual(len(result.bindings), 0)
        self.assertEqual(len(result.exclusions), 0)
        self.assertTrue(result.issues)

    def scope(
        self,
        *,
        reading="Table 47. Intermediate Compounds",
        outlined="Intermediate",
        raster=False,
    ):
        document, _structures, _boxes = original_catalogue(outlined=outlined)
        if raster:
            initial = source_layout(document[0])
            hints = [
                {**token, "source": "raster", "confidence": 0.99}
                for token in initial.native
            ]
            for token in hints:
                token.pop("native_paint", None)
            pixels = document[0].get_pixmap(matrix=fitz.Matrix(3, 3), alpha=False)
            width, height = document[0].rect.width, document[0].rect.height
            document.close()
            document = fitz.open()
            page = document.new_page(width=width, height=height)
            page.insert_image(page.rect, stream=pixels.tobytes("png"))
            tokens = SourceTokens(hints, source_layout(page), tuple(page.rect))
        else:
            page = document[0]
            layout = source_layout(page)
            tokens = SourceTokens(layout.native, layout)
        self.addCleanup(document.close)
        grids = detect_ruled_table_regions(page, dpi=240)
        with patch(
            "patent_sar_extractor.core.page_ocr_cache.get_ocr_engine",
            return_value=("rapidocr", self.engine(reading)),
        ):
            scope = observe_caption_role(page, grids[0], grids, tokens)
        return page, grids, tokens, scope

    def test_saved_proof_rejects_missing_weak_changed_and_malformed_sources(self):
        _page, _grids, _tokens, scope = self.scope()
        self.assertEqual(scope["role"], "nonfinal")
        original = json.loads(json.dumps(scope["sources"][0]["original_titles"][0]))
        self.assertEqual(
            source_title_text(original), "Table 47. Intermediate Compounds"
        )
        for change in (
            "missing_read",
            "weak_read",
            "changed_window",
            "missing_frame",
            "malformed_size",
        ):
            with self.subTest(change=change):
                proof = copy.deepcopy(original)
                if change == "missing_read":
                    proof["observations"].pop()
                elif change == "weak_read":
                    proof["observations"][1]["parts"][0]["confidence"] = 0.2
                elif change == "changed_window":
                    proof["bbox"][0] += 1
                elif change == "malformed_size":
                    proof["page_size"] = [None, 842]
                else:
                    proof["rendered_frames"].pop()
                self.assertIsNone(source_title_text(proof))

    def test_omitted_complete_source_cannot_use_prefixed_unknown_role_fallback(self):
        _page, _grids, _tokens, scope = self.scope(
            outlined="", reading="Table 47. Compounds"
        )
        changed = copy.deepcopy(scope)
        for parent in (*changed["sources"], *changed["observations"]):
            parent.pop("original_titles", None)
        for role in ("compound", "unknown"):
            changed["role"] = role
            self.assertIsNone(caption_role_status(changed, 1, changed["table_bbox"]))

    def test_actual_original_replay_checks_the_outlined_words_not_only_native_text(
        self,
    ):
        page, _grids, _tokens, scope = self.scope()
        proof = scope["sources"][0]["original_titles"][0]
        replay_source_title(page, proof)
        page.draw_rect(fitz.Rect(109, 78, 111, 80), fill=(0, 0, 0))
        with self.assertRaises(ValueError):
            replay_source_title(page, proof)

    def test_raster_title_uses_the_same_complete_text_and_original_pixel_replay(self):
        page, _grids, _tokens, scope = self.scope(
            outlined="", reading="Table 47. Compounds", raster=True
        )
        self.assertEqual(scope["role"], "compound")
        proof = scope["sources"][0]["original_titles"][0]
        replay_source_title(page, proof)
        pixmap = fitz.Pixmap(page.parent, page.get_images()[0][0])
        old = pixmap.pixel(180, 240)
        pixmap.set_pixel(180, 240, (255, 255, 255) if min(old) < 180 else (0, 0, 0))
        self.assertNotEqual(pixmap.pixel(180, 240), old)
        page.replace_image(page.get_images()[0][0], pixmap=pixmap)
        with (
            fitz.open(stream=page.parent.tobytes(), filetype="pdf") as changed,
            self.assertRaises(ValueError),
        ):
            replay_source_title(changed[0], proof)

    def test_existing_title_is_reused_only_after_actual_replay_without_another_ocr(
        self,
    ):
        from patent_sar_extractor.core.caption_role_observation import (
            owns_caption_frame,
        )

        page, grids, tokens, scope = self.scope(
            raster=True, outlined="", reading="Table 47. Compounds"
        )
        with patch(
            "patent_sar_extractor.core.page_ocr_cache.get_ocr_engine",
            side_effect=AssertionError("Reusing a title cannot acquire OCR"),
        ):
            self.assertTrue(
                owns_caption_frame(
                    page,
                    grids[0],
                    grids,
                    tokens,
                    [(80, 140, 140, 175), (210, 140, 270, 175)],
                    original_role=scope,
                )
            )

    def test_source_plan_carries_and_replays_titles_before_numbered_ocsr(self):
        from patent_sar_extractor.core.binding_original_replay import (
            original_binding_source_errors,
        )
        from patent_sar_extractor.core.ocsr.recognition_inputs import recognition_inputs
        from tests.test_heading_label_roles import HeadingLabelRoleTests

        control = HeadingLabelRoleTests(
            "test_full_binder_preserves_true_heading_but_reuses_exact_label_cell_roles"
        )
        control.setUp()
        self.addCleanup(control.doCleanups)
        with patch(
            "patent_sar_extractor.core.page_ocr_cache.get_ocr_engine", return_value=None
        ):
            source, _result, payload = control.run_binding()
        plan = recognition_inputs(payload)
        self.assertTrue(
            any(cell.get("method") == "original_title" for _, cell in plan.role_text)
        )
        with fitz.open(source) as document:
            errors = original_binding_source_errors(
                document,
                plan.formal,
                role_text=plan.role_text,
                plot_references=plan.plot_references,
                caption_references=plan.caption_references,
            )
            self.assertEqual(errors, [])
            document[0].draw_rect(fitz.Rect(50, 70, 52, 72), fill=(0, 0, 0))
            errors = original_binding_source_errors(
                document,
                plan.formal,
                role_text=plan.role_text,
                plot_references=plan.plot_references,
                caption_references=plan.caption_references,
            )
            self.assertTrue(errors)


if __name__ == "__main__":
    unittest.main()
