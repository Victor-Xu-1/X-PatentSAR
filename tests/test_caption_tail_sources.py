"""Generated closed caption rows, original page breaks and neighbour witnesses."""

import copy
import json
import unittest

import fitz

from patent_sar_extractor.artifact_catalog import expand_shared_json, pack_shared_json
from patent_sar_extractor.core.binding_auxiliary_replay import binding_text_cells
from patent_sar_extractor.core.caption_binding_proof import (
    valid_caption_binding_evidence,
)
from patent_sar_extractor.core.caption_grid_binding import bind_caption_grids
from patent_sar_extractor.core.caption_original_replay import (
    original_caption_source_errors,
)
from patent_sar_extractor.core.table_geometry import page_tokens
from tests.test_caption_role_continuation import binding, two_pages


class CaptionTailSourceTests(unittest.TestCase):
    def observe(self, *, footer=True, overhang=True, unknown=False):
        original, structures, boxes, grids, pages = two_pages(split=True)
        document = fitz.open()
        self.addCleanup(document.close)
        with original:
            if footer:
                original[0].insert_text((290, 800), "22", fontsize=9)
            for page in original:
                target = document.new_page(
                    width=page.rect.width, height=page.rect.height
                )
                target.insert_image(
                    target.rect,
                    stream=page.get_pixmap(matrix=fitz.Matrix(3, 3)).tobytes("png"),
                )

        def observed(page):
            tokens = page_tokens(page, dpi=200, allow_tesseract=False)
            if page.number == 0:
                if overhang:
                    for token in tokens:
                        if token["text"] in ("7E", "8E"):
                            # Layout nomination has a padded box; the independent
                            # original cell readers still observe the real ink.
                            token["bbox"] = [
                                *token["bbox"][:3],
                                grids[1][0]["ys"][-1] + 2,
                            ]
                if unknown:
                    tokens.append(
                        {
                            "text": "unassigned note",
                            "x": 25,
                            "y": 227,
                            "bbox": [15, 222, 35, 232],
                            "confidence": 0.99,
                            "source": "raster",
                            "geometry_space": "rendered",
                        }
                    )
            return tokens

        result = bind_caption_grids(
            document,
            structures,
            boxes,
            pages,
            grids_for_page=lambda page: grids[page.number + 1],
            tokens_for_page=observed,
        )
        return document, result

    def test_proved_external_caption_witness_does_not_taint_a_real_footer(self):
        _document, result = self.observe()
        self.assertEqual(result.issues, [])
        self.assertEqual(
            {pair["label"] for pair in result.bindings},
            {"41A", "89B", "7E", "8E", "73C", "104D"},
        )
        for pair in result.bindings:
            self.assertTrue(valid_caption_binding_evidence(binding(pair)))

    def test_unowned_boundary_is_not_ignored_when_the_tail_text_is_empty(self):
        _document, result = self.observe(footer=False, overhang=False, unknown=True)
        self.assertFalse(any(pair["label"] == "7E" for pair in result.bindings))
        self.assertTrue(result.issues)

    def test_ownership_witness_is_required_after_serialization(self):
        _document, result = self.observe()
        pair = next(pair for pair in result.bindings if pair["label"] == "7E")
        item = binding(pair)
        self.assertTrue(valid_caption_binding_evidence(item))
        tail = item["exact_caption_evidence"]["ownership"]["page_boundary"][
            "previous_tail"
        ]
        self.assertTrue(tail["caption_cells"])
        for change in (
            lambda tail: tail.pop("caption_cells"),
            lambda tail: tail.update(version=True),
            lambda tail: tail["caption_cells"][0].update(label="different"),
            lambda tail: tail["caption_cells"][0].update(page_no=2),
            lambda tail: tail["caption_cells"][0].update(bbox=[0, 0, 20, 20]),
            lambda tail: tail["caption_cells"][0].update(observations=[]),
            lambda tail: tail["caption_cells"][0]["observations"][0].pop(
                "source_observation"
            ),
            lambda tail: tail["chunks"][0]["sources"][0].update(
                text="different footer"
            ),
            lambda tail: tail["chunks"][0]["sources"][0]["tokens"][0].update(
                confidence=0.2
            ),
        ):
            changed = copy.deepcopy(item)
            change(
                changed["exact_caption_evidence"]["ownership"]["page_boundary"][
                    "previous_tail"
                ]
            )
            self.assertFalse(valid_caption_binding_evidence(changed))

    def test_later_bindings_replay_the_prior_owner_even_without_its_bound_record(self):
        document, result = self.observe()
        selected = [
            binding(next(pair for pair in result.bindings if pair["label"] == "73C"))
        ]
        self.assertEqual(original_caption_source_errors(document, selected), [])
        # A later same-page assignment needs its inherited original context,
        # even when this consumer was not also given the earlier molecules.
        self.assertIn(1, {page for page, _cell in binding_text_cells(selected)})
        document[0].insert_text((68, 224), "X", fontsize=8)
        self.assertTrue(valid_caption_binding_evidence(selected[0]))
        self.assertTrue(original_caption_source_errors(document, selected))

    def test_shared_json_keeps_raw_boundary_witness_and_cell_proof_distinct(self):
        document, result = self.observe()
        selected = [binding(pair) for pair in result.bindings]
        before = copy.deepcopy(selected)
        restored = expand_shared_json(
            json.loads(json.dumps(pack_shared_json({"bindings": selected})))
        )["bindings"]
        self.assertEqual(restored, before)
        cross = next(row for row in restored if row["cpd"] == "Compound 7E")
        tail = cross["exact_caption_evidence"]["ownership"]["page_boundary"][
            "previous_tail"
        ]
        self.assertEqual(tail["chunks"][0]["sources"][0]["status"], "unqualified")
        self.assertTrue(tail["chunks"][0]["sources"][0]["boundary_tokens"])
        self.assertTrue(valid_caption_binding_evidence(cross))
        self.assertEqual(original_caption_source_errors(document, restored), [])

    def test_legacy_tail_is_readable_but_never_current_carry_proof(self):
        document, result = self.observe()
        selected = [
            binding(next(pair for pair in result.bindings if pair["label"] == "73C"))
        ]
        role = selected[0]["exact_caption_evidence"]["ownership"]["caption_role"]
        tail = role["continuation"]["previous_tail"]
        tail.pop("version")
        tail.pop("caption_cells")
        self.assertTrue(list(binding_text_cells(selected)))
        self.assertFalse(valid_caption_binding_evidence(selected[0]))
        self.assertTrue(original_caption_source_errors(document, selected))
