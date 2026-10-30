"""Current continuation declarations join the registered original source, not OCR votes."""

import copy
import unittest
import zlib
from types import SimpleNamespace
from unittest.mock import patch

import fitz
import numpy as np
import test_lateral_column_continuation as continuation_controls
from lateral_structure_support import LateralStructureControls

from patent_sar_extractor.core.binding_source_references import (
    reference_issues,
    reference_scope,
)
from patent_sar_extractor.core.boundary_cell_pixels import observe_boundary_cell
from patent_sar_extractor.core.cell_raster import cell_pixel_rect
from patent_sar_extractor.core.formal_structure import coverage_errors
from patent_sar_extractor.core.plot_reference_pixels import retained_pixels
from patent_sar_extractor.core.source_cell_pixels import (
    closed_cell_masks,
    closed_masks_are_empty,
    observe_closed_cell,
)
from patent_sar_extractor.core.source_evidence_identity import proof_id
from patent_sar_extractor.core.structure_declaration_scopes import (
    declaration_page_id,
    declaration_scopes,
)
from patent_sar_extractor.core.title_context_grids import title_context_spec
from patent_sar_extractor.core.title_ink_geometry import title_ink_rows
from patent_sar_extractor.core.title_ink_source import (
    observe_title_ink,
    replay_title_ink,
)


class DeclarationContinuationSourceTests(LateralStructureControls, unittest.TestCase):
    continued_tables = (
        continuation_controls.LateralColumnContinuationTests.continued_tables
    )

    def original(self, *, same_page=False, raster=False):
        _result, payload = self.run_case(
            raster=raster,
            mutate_document=lambda d, r: self.continued_tables(
                d, r, same_page=same_page
            ),
        )
        page = next(
            s
            for s in payload["source_sections"]
            if s["role"] == "structure_declaration_page"
            and s["page_no"] == (1 if same_page else 2)
        )
        self.assertEqual(page["source"]["version"], 4)
        self.assertEqual(len(page["source"]["continued_columns"]), 2)
        return payload, page

    def test_same_page_continuation_preserves_native_and_raster_source_closure(self):
        for raster in (False, True):
            with self.subTest(raster=raster):
                payload, _page = self.original(same_page=True, raster=raster)
                self.assertEqual(len(payload["compound_catalog"]["entries"]), 8)
                self.assertEqual(coverage_errors(payload), [])

    def test_rule_only_carrier_cannot_replace_current_or_body_cell_evidence(self):
        _payload, page = self.original(same_page=True)
        ink = next(
            copy.deepcopy(parent["title_context"]["ink_source"])
            for scope in page["source"]["catalogue_scopes"]
            for parent in scope["sources"]
            if scope["table_bbox"][1] > 400
        )
        current = ink["ruling_sources"][0]
        with fitz.open(self.root / "original.pdf") as document:
            current["pixels"] = observe_boundary_cell(document[0], current["cell"])
        self.assertIsNotNone(current["pixels"])
        self.assertIsNone(title_ink_rows(ink))

    def test_attached_ink_on_a_preceding_closing_rule_is_not_erased(self):
        def changed(document, records):
            self.continued_tables(document, records, same_page=True)
            document[0].draw_line((80, 330), (80, 350))

        for raster in (False, True):
            with self.subTest(raster=raster):
                _result, payload = self.run_case(raster=raster, mutate_document=changed)
                self.assertTrue(coverage_errors(payload))

    def test_headerless_page_reuses_complete_column_proof_without_rewriting_raw_titles(
        self,
    ):
        payload, page = self.original()
        scopes = declaration_scopes(page["source"])
        self.assertEqual(coverage_errors(payload), [])
        self.assertEqual([s["role"] for s in scopes], ["compound", "compound"])
        self.assertTrue(all(s.get("continuation_source_region") for s in scopes))
        self.assertTrue(all(not s["unproved_title"] for s in scopes))
        self.assertEqual(
            [s["role"] for s in page["source"]["catalogue_scopes"]],
            ["unknown", "unknown"],
        )

    def test_rehashed_omission_or_version_downgrade_cannot_waive_a_continuation(self):
        payload, _page = self.original()
        for operation in ("remove", "downgrade"):
            saved = copy.deepcopy(payload)
            page = next(
                s
                for s in saved["source_sections"]
                if s["role"] == "structure_declaration_page" and s["page_no"] == 2
            )
            if operation == "remove":
                page["source"]["continued_columns"].pop()
            else:
                page["source"].pop("continued_columns")
                page["source"].pop("logical_columns")
                page["source"]["version"] = 2
            page["region_id"] = declaration_page_id(page["source"])
            saved["source_reference_scope"] = reference_scope(saved["source_sections"])
            with self.subTest(operation=operation), self.assertRaises(ValueError):
                reference_issues(saved, saved["compound_catalog"]["entries"])

    def test_changed_foreign_column_source_or_original_grid_cannot_supply_a_role(self):
        _payload, page = self.original()
        for operation in ("foreign", "grid", "duplicate"):
            source = copy.deepcopy(page["source"])
            column = source["continued_columns"][0]
            if operation == "foreign":
                column["source"]["header_scope"]["original_pdf_sha256"] = "f" * 64
                column["region_id"] = proof_id(column["source"])
            elif operation == "grid":
                source["page_grids"].pop()
            else:
                source["continued_columns"].append(copy.deepcopy(column))
            with self.subTest(operation=operation), self.assertRaises(ValueError):
                declaration_page_id(source)

    def test_unowned_original_prefix_never_becomes_an_empty_continuation(self):
        def changed(document, records):
            self.continued_tables(document, records)
            document[1].insert_text(
                (40, 40), "A different experiment was performed.", fontsize=9
            )

        _result, payload = self.run_case(mutate_document=changed)
        page = next(
            s
            for s in payload["source_sections"]
            if s["role"] == "structure_declaration_page" and s["page_no"] == 2
        )
        self.assertTrue(coverage_errors(payload))
        scopes = declaration_scopes(page["source"])
        self.assertFalse(any(s.get("continuation_source_region") for s in scopes))


class BoundaryCellPixelTests(unittest.TestCase):
    def test_legacy_ink_inventory_replays_without_retagging_saved_sources(self):
        with fitz.open() as document:
            page = document.new_page(width=460, height=320)
            page.insert_text((40, 60), "Table 52. Selected compounds", fontsize=10)
            source = observe_title_ink(
                page, [0, 0, 460, 100], title_context_spec(), version=4
            )
            before = copy.deepcopy(source)
            self.assertIsNotNone(title_ink_rows(source))
            replay_title_ink(page, source)
            self.assertEqual(source, before)
            self.assertEqual(source["version"], 4)
            page.insert_text((40, 90), "Unowned new source", fontsize=10)
            with self.assertRaises(ValueError):
                replay_title_ink(page, source)

    def observed(self):
        document = fitz.open()
        self.addCleanup(document.close)
        page = document.new_page(width=460, height=320)
        cell = [40, 60, 360, 230]
        page.draw_rect(fitz.Rect(cell))
        page.insert_text((130, 150), "Unobserved interior", fontsize=10)
        packet = observe_boundary_cell(page, cell)
        self.assertIsNotNone(packet)
        return document, cell, packet

    def test_all_four_paired_edges_are_rule_only_never_full_cell_or_blankness(self):
        _document, cell, packet = self.observed()
        masks = closed_cell_masks(packet, cell, [460, 320], boundary_only=True)
        self.assertEqual(len(masks), 2)
        self.assertTrue(all(mask.any() for mask in masks))
        self.assertIsNone(closed_cell_masks(packet, cell, [460, 320]))
        self.assertIsNone(
            closed_cell_masks(packet, cell, [460, 320], content_only=True)
        )
        self.assertFalse(closed_masks_are_empty(None))

    def test_missing_reordered_or_foreign_edge_sources_cannot_prove_closure(self):
        _document, cell, original = self.observed()
        for operation in ("missing", "reorder", "box", "version"):
            packet = copy.deepcopy(original)
            if operation == "missing":
                packet["strips"].pop()
            elif operation == "reorder":
                packet["strips"].reverse()
            elif operation == "box":
                packet["strips"][0]["bbox"][0] += 1
            else:
                packet["version"] = True
            with self.subTest(operation=operation):
                self.assertIsNone(
                    closed_cell_masks(packet, cell, [460, 320], boundary_only=True)
                )

    def test_original_boundary_change_cannot_reuse_its_saved_strip_source(self):
        document, cell, packet = self.observed()
        document[0].draw_rect(
            fitz.Rect(35, 55, 365, 65), fill=(1, 1, 1), color=(1, 1, 1)
        )
        self.assertNotEqual(observe_boundary_cell(document[0], cell), packet)

    def test_over_budget_geometry_refuses_before_rendering_or_model_loading(self):
        page = SimpleNamespace(rect=SimpleNamespace(width=10000, height=10000))
        with patch(
            "patent_sar_extractor.core.boundary_cell_pixels.observe_pixels",
            side_effect=AssertionError("Over-budget source must refuse before render"),
        ):
            self.assertIsNone(observe_boundary_cell(page, [10, 10, 9990, 9990]))

    def test_ordinary_full_cell_content_and_blankness_keep_the_original_contract(self):
        with fitz.open() as document:
            page = document.new_page(width=460, height=320)
            cell = [40, 60, 360, 230]
            page.draw_rect(fitz.Rect(cell))
            packet = observe_closed_cell(page, cell)
            self.assertIsNotNone(packet)
            self.assertIsNotNone(closed_cell_masks(packet, cell, [460, 320]))
            self.assertTrue(
                closed_masks_are_empty(
                    closed_cell_masks(packet, cell, [460, 320], content_only=True)
                )
            )

    def test_corner_disagreement_can_only_remove_rule_pixels_not_invent_them(self):
        document, cell, packet = self.observed()
        full = cell_pixel_rect(packet["bbox"], 400)
        left, top = packet["strips"][0], packet["strips"][2]
        a, b = cell_pixel_rect(left["bbox"], 400), cell_pixel_rect(top["bbox"], 400)
        original = closed_cell_masks(packet, cell, [460, 320], boundary_only=True)[0]
        candidates = [
            (y, x)
            for y, x in zip(*np.where(original))
            if max(a.x0, b.x0) <= x + full.x0 < min(a.x1, b.x1)
            and max(a.y0, b.y0) <= y + full.y0 < min(a.y1, b.y1)
        ]
        self.assertTrue(candidates)
        y, x = candidates[len(candidates) // 2]
        reading = left["readings"][0]
        bits = retained_pixels(reading, left["bbox"], 400, 8_000_000).copy()
        bits[y + full.y0 - a.y0, x + full.x0 - a.x0] = 0
        reading["mask_hex"] = zlib.compress(np.packbits(bits).tobytes()).hex()
        masks = closed_cell_masks(packet, cell, [460, 320], boundary_only=True)
        self.assertTrue(masks is None or not masks[0][y, x])
        self.assertNotEqual(observe_boundary_cell(document[0], cell), packet)


if __name__ == "__main__":
    unittest.main()
