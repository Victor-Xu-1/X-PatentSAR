"""Closed physical scope never upgrades unknown labels or replaces original replay."""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz

from patent_sar_extractor.artifact_catalog import expand_shared_json, pack_shared_json
from patent_sar_extractor.core.binding_artifacts import write_binding_result
from patent_sar_extractor.core.binding_auxiliary_replay import binding_text_cells
from patent_sar_extractor.core.caption_binding_proof import (
    valid_caption_binding_evidence,
)
from patent_sar_extractor.core.caption_boundary_context import valid_caption_tail
from patent_sar_extractor.core.caption_grid_binding import bind_caption_grids
from patent_sar_extractor.core.caption_original_replay import (
    original_caption_source_errors,
)
from patent_sar_extractor.core.caption_tail_sources import caption_tail_source_packets
from patent_sar_extractor.core.cell_rendering import CellRenderLimit
from patent_sar_extractor.core.source_geometry import SourceTokens, source_layout
from patent_sar_extractor.web.files import SafeFiles
from tests import test_caption_unresolved_cell_boundary as boundary
from tests.test_caption_role_continuation import binding, two_pages


class ClosedCaptionReplayTests(unittest.TestCase):
    observe = boundary.UnresolvedCaptionBoundaryTests.observe

    def selected(self):
        result = self.observe()
        item = binding(next(pair for pair in result.bindings if pair["label"] == "73C"))
        role = item["exact_caption_evidence"]["ownership"]["caption_role"][
            "continuation"
        ]["previous"]
        tail = item["exact_caption_evidence"]["ownership"]["caption_role"][
            "continuation"
        ]["previous_tail"]
        self.assertTrue(any("closed_scope" in owner for owner in tail["caption_cells"]))
        return item, tail, role

    def test_later_source_alone_replays_the_unknown_cell_without_starting_ocr(self):
        item, tail, _role = self.selected()
        physical = next(
            owner for owner in tail["caption_cells"] if "closed_scope" in owner
        )
        self.assertNotIn("label", physical)
        self.assertNotIn("bare", physical)
        self.assertTrue(valid_caption_binding_evidence(item))
        self.assertIn(1, {page for page, _cell in binding_text_cells([item])})
        with patch(
            "patent_sar_extractor.core.table_cells.get_ocr_engine",
            side_effect=AssertionError("Original replay must not start OCR"),
        ):
            self.assertEqual(original_caption_source_errors(self.document, [item]), [])

    def test_changed_outside_pixels_refuse_even_when_the_cell_itself_is_unchanged(self):
        item, _tail, _role = self.selected()
        self.assertEqual(original_caption_source_errors(self.document, [item]), [])
        # Outside the actual closed cell but inside the retained support view.
        self.document[0].draw_rect(
            fitz.Rect(105, 230.8, 107, 231.3), color=None, fill=(0.9, 0.9, 0.9)
        )
        self.assertTrue(valid_caption_binding_evidence(item))
        self.assertTrue(original_caption_source_errors(self.document, [item]))

    def test_shared_serialization_keeps_unqualified_text_and_physical_proof_distinct(
        self,
    ):
        item, tail, _role = self.selected()
        before = copy.deepcopy(item)
        restored = expand_shared_json(
            json.loads(json.dumps(pack_shared_json({"bindings": [item]})))
        )["bindings"][0]
        self.assertEqual(restored, before)
        self.assertTrue(valid_caption_binding_evidence(restored))
        self.assertEqual(original_caption_source_errors(self.document, [restored]), [])
        physical = next(
            owner for owner in tail["caption_cells"] if "closed_scope" in owner
        )
        self.assertTrue(
            any(
                "uncertain" in str(reading.get("raw_text", reading.get("text", "")))
                for reading in physical["observations"]
            )
        )

    def test_sole_writer_and_safe_reader_keep_unknown_source_without_upgrading_it(self):
        item, _tail, _role = self.selected()
        item["binding_rule"] = "original_caption_cell"
        issue = {
            "reason": "unread_or_conflicting_caption",
            "page_no": 1,
            "evidence": {"raw_text": "uncertain note"},
        }
        with tempfile.TemporaryDirectory(prefix="closed-caption-writer-") as directory:
            root = Path(directory)
            write_binding_result(
                root,
                patent_id="CONTROLLED-CLOSED-CAPTION",
                bindings=[item],
                detected_style="original_cell_caption_heading",
                include_intermediates=False,
                total_structures=2,
                total_compound_blocks=2,
                table_pages=[1, 2],
                table_covered_count=1,
                no_binding=[],
                unbound_pages=[],
                source_issues=[issue],
                original_pdf_sha256="a" * 64,
            )
            restored = SafeFiles(root).json("bindings.json", optional=False)
        rows = restored["compound_catalog"]["entries"]
        self.assertEqual([row["cpd"] for row in rows], ["Compound 73C"])
        self.assertIn(issue, restored["source_issues"])
        self.assertEqual(
            rows[0]["exact_caption_evidence"], item["exact_caption_evidence"]
        )
        self.assertTrue(valid_caption_binding_evidence(rows[0]))
        self.assertEqual(original_caption_source_errors(self.document, rows), [])

    def test_malformed_or_changed_support_cannot_authorize_a_carry(self):
        _item, tail, role = self.selected()
        self.assertTrue(valid_caption_tail(tail, role))
        for mutate in (
            lambda owner: owner.pop("closed_scope"),
            lambda owner: owner.update(page_no=2),
            lambda owner: owner.update(observations=[]),
            lambda owner: owner["closed_scope"].update(version=True),
            lambda owner: owner["closed_scope"].update(views=[]),
            lambda owner: owner["closed_scope"].update(bounds=[0, 0, 1, 1]),
            lambda owner: owner["closed_scope"]["views"][0].update(closed_bands=[]),
            lambda owner: owner["closed_scope"]["views"][0]["frame"].update(
                pixel_sha256="0" * 64
            ),
            lambda owner: owner["closed_scope"]["views"][0]["window"].update(
                purpose="text"
            ),
        ):
            changed = copy.deepcopy(tail)
            owner = next(
                owner for owner in changed["caption_cells"] if "closed_scope" in owner
            )
            mutate(owner)
            self.assertFalse(valid_caption_tail(changed, role))

    def test_a_physical_scope_cannot_claim_witness_ink_beyond_its_support(self):
        _item, tail, role = self.selected()
        changed = copy.deepcopy(tail)
        physical = next(
            owner for owner in changed["caption_cells"] if "closed_scope" in owner
        )
        for chunk in changed["chunks"]:
            for source in chunk["sources"]:
                for token in source.get("boundary_tokens", []):
                    if token["text"] == "note":
                        token["bbox"][3] = physical["closed_scope"]["bounds"][3] + 1
        for reading in physical["observations"]:
            for token in reading.get("source_observation", {}).get("tokens", []):
                if token["text"] == "note":
                    token["bbox"][3] = physical["closed_scope"]["bounds"][3] + 1
        self.assertFalse(valid_caption_tail(changed, role))

    def test_legacy_v2_tail_cannot_introduce_a_new_physical_only_owner(self):
        item, tail, role = self.selected()
        tail["version"] = 2
        self.assertFalse(valid_caption_tail(tail, role))
        with self.assertRaisesRegex(ValueError, "physical scope"):
            list(caption_tail_source_packets([item]))

    def test_support_budget_refusal_keeps_original_unknown_and_blocks_carry(self):
        with patch(
            "patent_sar_extractor.core.caption_cell_pixels.render_cell_raster",
            side_effect=CellRenderLimit("Controlled finite support budget"),
        ):
            result = self.observe()
        self.assertFalse({"73C", "104D"} & {pair["label"] for pair in result.bindings})
        self.assertTrue(result.issues)

    def test_known_v2_identity_inventory_is_readable_but_not_current_carry_proof(self):
        document, structures, boxes, grids, pages = two_pages(split=True)
        self.addCleanup(document.close)
        result = bind_caption_grids(
            document,
            structures,
            boxes,
            pages,
            grids_for_page=lambda page: grids[page.number + 1],
            tokens_for_page=lambda page: SourceTokens(
                source_layout(page).native, source_layout(page)
            ),
        )
        item = binding(next(pair for pair in result.bindings if pair["label"] == "73C"))
        self.assertTrue(valid_caption_binding_evidence(item))
        link = item["exact_caption_evidence"]["ownership"]["caption_role"][
            "continuation"
        ]
        link["previous_tail"]["version"] = 2
        self.assertEqual(list(caption_tail_source_packets([item])), [])
        self.assertFalse(valid_caption_binding_evidence(item))
        self.assertTrue(original_caption_source_errors(document, [item]))
