"""Native text is not proof that every printed source mark has been read."""

import copy
import hashlib
import json
import unittest
from contextlib import contextmanager, nullcontext
from unittest.mock import patch

import fitz

from patent_sar_extractor.core.activity_auxiliary_replay import (
    original_activity_source_errors,
)
from patent_sar_extractor.core.activity_grid_cells import read_activity_cell
from patent_sar_extractor.core.heading_observation import observe_heading
from patent_sar_extractor.core.heading_original_replay import validate_original_heading
from patent_sar_extractor.core.heading_source_proof import proved_heading_declaration
from patent_sar_extractor.core.native_cell_replay import original_native_cell_matches
from patent_sar_extractor.core.native_window_coverage import (
    native_window_complete,
    observe_native_window,
    valid_native_window,
)
from patent_sar_extractor.core.source_cell_claims import cell_source_status
from patent_sar_extractor.core.source_geometry import SourceTokens, source_layout
from patent_sar_extractor.core.source_paint_visibility import native_paint_view


@contextmanager
def original_cell(*, prefix="", value="Compound 11", outlined=False):
    """Real PDF paths and text, not invented source tokens or visibility flags."""
    with fitz.open() as reference:
        first = reference.new_page(width=500, height=360)
        whole = f"{prefix} {value}" if prefix else value
        first.insert_text((40, 65), whole, fontsize=11)
        words = first.get_text("words")
        bounds = [
            min(w[0] for w in words),
            min(w[1] for w in words),
            max(w[2] for w in words),
            max(w[3] for w in words),
        ]
    with fitz.open() as original:
        page = original.new_page(width=500, height=360)
        offset = 0
        if prefix and outlined:
            with fitz.open() as lettering:
                source = lettering.new_page(width=500, height=360)
                source.insert_text((40, 65), prefix, fontsize=11)
                svg = source.get_svg_image(text_as_path=True).encode()
                with (
                    fitz.open(stream=svg, filetype="svg") as image,
                    fitz.open(stream=image.convert_to_pdf(), filetype="pdf") as paths,
                ):
                    assert not paths[0].get_text().strip()
                    page.show_pdf_page(page.rect, paths, 0)
            offset = fitz.get_text_length(prefix + " ", fontsize=11)
        page.insert_text((40 + offset, 65), value if outlined else whole, fontsize=11)
        page.insert_text((40, 330), "Independent footer", fontsize=9)
        yield (
            original,
            page,
            {
                "text": whole,
                "bbox": bounds,
                "source": "page_ocr" if outlined else "native",
                "geometry_space": "rendered",
            },
        )


def heading(page, nomination):
    digest = hashlib.sha256(page.parent.tobytes(no_new_id=True)).hexdigest()
    return observe_heading(page, nomination, digest, grids=[])


def source_tokens(page):
    layout = source_layout(page)
    return SourceTokens(layout.native, layout, layout.raster_bounds)


class NativeHeadingCoverageTests(unittest.TestCase):
    def test_outline_nonfinal_role_cannot_disappear_behind_a_native_number(self):
        for prefix in ("Intermediate", "Preparation of intermediate"):
            with (
                self.subTest(prefix=prefix),
                original_cell(prefix=prefix, outlined=True) as (_, page, nomination),
                patch(
                    "patent_sar_extractor.core.heading_observation.get_ocr_engine",
                    return_value=None,
                ),
            ):
                proof = heading(page, nomination)
                self.assertIsNone(proved_heading_declaration(proof))

    def test_complete_native_titles_keep_literal_roles_and_start_no_ocr(self):
        for prefix, expected in (
            ("", "compound_heading"),
            ("Intermediate", "intermediate_section"),
        ):
            with (
                self.subTest(prefix=prefix),
                original_cell(prefix=prefix) as (_, page, nomination),
                patch(
                    "patent_sar_extractor.core.heading_observation.get_ocr_engine",
                    side_effect=AssertionError("Complete native text needs no OCR"),
                ),
            ):
                proof = heading(page, nomination)
                self.assertEqual(proved_heading_declaration(proof)["role"], expected)
                self.assertEqual(proof["observations"], [])
                validate_original_heading(page, proof)

    def test_actual_original_replay_refuses_unobserved_outline_ink(self):
        with original_cell() as (_, page, nomination):
            proof = heading(page, nomination)
            changed = copy.deepcopy(proof)
            # Keep the complete original native text and locator unchanged.
            # The newly printed mark is inside the saved heading window.
            bounds = changed["bbox"]
            page.draw_rect(
                fitz.Rect(
                    bounds[0] + 0.2, bounds[1] + 0.2, bounds[0] + 1, bounds[1] + 1
                ),
                color=None,
                fill=(0, 0, 0),
            )
            with self.assertRaises(ValueError):
                validate_original_heading(page, changed)

    def test_outlined_relation_prevents_unqualified_native_measurement_acceptance(self):
        with original_cell(prefix="<", value="0.4", outlined=True) as (_, page, _):
            _, readings, review = read_activity_cell(
                page,
                source_tokens(page),
                [30, 40, 150, 85],
                identifier=False,
                native=True,
            )
            self.assertTrue(review)
            self.assertEqual(cell_source_status(readings[0]), "unqualified")
            self.assertFalse(original_native_cell_matches(page, readings[0]))

    def test_saved_activity_replay_cannot_certify_a_partial_native_layer(self):
        with original_cell(prefix="<", value="0.4", outlined=True) as (doc, page, _):
            _, readings, _ = read_activity_cell(
                page,
                source_tokens(page),
                [30, 40, 150, 85],
                identifier=False,
                native=True,
            )
            payload = {
                "rows": [
                    {
                        "activity_sources": [
                            {"page_no": 1, "cells": [{"observations": readings}]}
                        ]
                    }
                ]
            }
            self.assertTrue(
                original_activity_source_errors(
                    payload, open_original=lambda: nullcontext(doc)
                )
            )

    def test_ordinary_closed_native_cells_remain_qualified_without_ocr(self):
        with original_cell(value="0.4") as (doc, page, _):
            bounds = [30, 40, 150, 85]
            for x in (bounds[0], bounds[2]):
                page.draw_line((x, bounds[1]), (x, bounds[3]))
            for y in (bounds[1], bounds[3]):
                page.draw_line((bounds[0], y), (bounds[2], y))
            value, readings, review = read_activity_cell(
                page, source_tokens(page), bounds, identifier=False, native=True
            )
            self.assertEqual(value, "0.4")
            self.assertFalse(review)
            self.assertTrue(original_native_cell_matches(page, readings[0]))
            payload = {
                "rows": [
                    {
                        "activity_sources": [
                            {"page_no": 1, "cells": [{"observations": readings}]}
                        ]
                    }
                ]
            }
            self.assertEqual(
                original_activity_source_errors(
                    payload, open_original=lambda: nullcontext(doc)
                ),
                [],
            )

    def test_enclosing_but_disjoint_rule_is_not_extra_heading_ink(self):
        with (
            original_cell() as (_, page, nomination),
            patch(
                "patent_sar_extractor.core.heading_observation.get_ocr_engine",
                side_effect=AssertionError("A disjoint frame needs no OCR"),
            ),
        ):
            page.draw_rect(fitz.Rect(20, 35, 270, 90))
            proof = heading(page, nomination)
            self.assertEqual(
                proved_heading_declaration(proof)["role"], "compound_heading"
            )
            validate_original_heading(page, proof)

    def test_border_geometry_cannot_hide_interior_or_attached_unknown_ink(self):
        for mode in ("missing_edge", "interior", "attached"):
            with self.subTest(mode=mode), original_cell(value="0.4") as (_, page, _):
                bounds = [30, 40, 150, 85]
                if mode == "missing_edge":
                    page.draw_line((30, 40), (150, 40))
                else:
                    page.draw_rect(fitz.Rect(bounds))
                    if mode == "interior":
                        page.draw_line((70, 70), (80, 75))
                    else:
                        page.draw_line((30, 58), (35, 58))
                _, _, review = read_activity_cell(
                    page, source_tokens(page), bounds, identifier=False, native=True
                )
                self.assertTrue(review)

    def test_serialized_native_window_cannot_be_removed_or_relabelled(self):
        with original_cell() as (_, page, nomination):
            proof = json.loads(json.dumps(heading(page, nomination)))
            changes = []
            removed = copy.deepcopy(proof)
            removed.pop("native_window")
            changes.append(removed)
            for field, value in (
                ("paint_count", True),
                ("paints", []),
                ("refusal", "paint_budget"),
            ):
                changed = copy.deepcopy(proof)
                changed["native_window"][field] = value
                changes.append(changed)
            changed = copy.deepcopy(proof)
            changed["native_window"]["paints"][0]["text"] = "Compound 12"
            changes.append(changed)
            for changed in changes:
                with self.subTest(keys=list(changed)), self.assertRaises(ValueError):
                    validate_original_heading(page, changed)

    def test_over_budget_source_retains_refusal_not_a_successful_prefix(self):
        with original_cell(value="0.4") as (_, page, _):
            bounds = [30, 40, 150, 85]
            page.draw_rect(fitz.Rect(bounds))
            page.draw_line((70, 70), (80, 75))
            tokens = source_tokens(page)
            from patent_sar_extractor.core.source_observations import (
                source_cell_observation,
            )

            profile = source_cell_observation(tokens, bounds, native=True)
            with patch(
                "patent_sar_extractor.core.native_window_coverage.MAX_WINDOW_PAINTS", 2
            ):
                packet = observe_native_window(page, bounds)
                self.assertGreater(packet["paint_count"], 2)
                self.assertEqual(packet["paints"], [])
                self.assertEqual(packet["refusal"], "paint_budget")
                self.assertTrue(valid_native_window(packet, bounds))
                self.assertFalse(native_window_complete(packet, profile))

    def test_paint_facts_from_another_original_page_cannot_supply_coverage(self):
        with original_cell() as (_, first, nomination):
            view = native_paint_view(first)
            with original_cell() as (_, second, _), self.assertRaises(ValueError):
                observe_native_window(second, nomination["bbox"], paint_view=view)

    def test_scalar_and_identifier_cell_fast_paths_share_the_same_coverage_gate(self):
        from patent_sar_extractor.core.table_cells import read_cell

        for prefix, text, kind in (
            ("<", "0.4", "number"),
            ("Intermediate", "Compound 11", "label"),
        ):
            with (
                self.subTest(kind=kind),
                original_cell(prefix=prefix, value=text, outlined=True) as (_, page, _),
            ):
                result = read_cell(
                    page, [30, 40, 280, 85], source_tokens(page), kind, True
                )
                self.assertTrue(result.needs_review)
                self.assertEqual(
                    cell_source_status(result.observations[0]), "unqualified"
                )
                self.assertFalse(
                    original_native_cell_matches(page, result.observations[0])
                )

    def test_shared_original_text_paint_does_not_merge_or_drop_independent_rows(self):
        from patent_sar_extractor.core.activity_text_capture import capture_text_page
        from patent_sar_extractor.core.activity_text_sources import text_page_qualified

        with fitz.open() as document:
            page = document.new_page(width=500, height=360)
            page.insert_text(
                (40, 60), "Table T. Binding\nNo. | IC50 (nM)\n17 | 0.4", fontsize=10
            )
            self.assertEqual(len(page.get_bboxlog()), 1)
            with patch(
                "patent_sar_extractor.core.activity_text_capture.get_ocr_engine",
                side_effect=AssertionError("Complete native rows need no model"),
            ):
                source = capture_text_page(page, page.get_text("text"))
            self.assertTrue(text_page_qualified(source, page.get_text("text")))
            self.assertEqual(
                "\n".join(line["text"] for line in source["lines"]).splitlines(),
                ["Table T. Binding", "No. | IC50 (nM)", "17 | 0.4"],
            )

    def test_boundary_identity_cannot_replace_the_actual_closed_original(self):
        with original_cell(value="0.4") as (_, page, _):
            bounds = [30, 40, 150, 85]
            page.draw_rect(fitz.Rect(bounds))
            _, readings, review = read_activity_cell(
                page, source_tokens(page), bounds, identifier=False, native=True
            )
            self.assertFalse(review)
            self.assertIsNotNone(readings[0]["native_window"]["boundary_source_id"])
            forged = copy.deepcopy(readings[0])
            forged["native_window"]["boundary_source_id"] = "a" * 64
            self.assertFalse(original_native_cell_matches(page, forged))
            page.draw_line((30, 58), (36, 58))
            self.assertFalse(original_native_cell_matches(page, readings[0]))

    def test_primitive_budget_and_malformed_windows_never_become_native_votes(self):
        with original_cell(value="0.4") as (_, page, _):
            bounds = [30, 40, 150, 85]
            page.draw_rect(fitz.Rect(bounds))
            with patch(
                "patent_sar_extractor.core.native_window_coverage.MAX_WINDOW_PRIMITIVES",
                1,
            ):
                packet = observe_native_window(page, bounds)
                self.assertEqual(packet["refusal"], "primitive_budget")
                self.assertEqual(packet["paints"], [])
                self.assertTrue(valid_native_window(packet, bounds))
            for malformed in (None, {}, {"version": True}, {"bbox": None}):
                self.assertFalse(valid_native_window(malformed, None))


if __name__ == "__main__":
    unittest.main()
