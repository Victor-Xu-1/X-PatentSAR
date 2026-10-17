"""Unparsed page hints never decide the original caption's identifier form."""

import copy
import json
import unittest

from patent_sar_extractor.core.caption_binding_proof import (
    valid_caption_binding_evidence,
)
from patent_sar_extractor.core.caption_grid_binding import bind_caption_grids
from patent_sar_extractor.core.caption_grid_rows import caption_rows
from patent_sar_extractor.core.table_geometry import (
    detect_ruled_table_regions,
    page_tokens,
)
from tests.test_caption_role_raster import raster_catalog


def formal_binding(pair):
    return {
        "cpd": f"Compound {pair['label']}",
        "structure_id": pair["structure"]["id"],
        "page_no": pair["structure"]["page_no"],
        **{
            f"struct_{axis}": pair["structure"][axis]
            for axis in ("x0", "y0", "x1", "y1")
        },
        "binding_rule": "original_caption_cell",
        "exact_caption_evidence": {
            "page_no": pair["label_page_no"],
            "bbox": list(pair["label_bbox"]),
            "observations": pair["observations"],
            "ownership": pair["ownership"],
        },
    }


def changed_caption_hints(tokens, grid, hint):
    """Inject only a synthetic page-reader fault; original raster pixels stay."""
    tokens = copy.deepcopy(tokens)
    remove = set()
    for x0, x1 in zip(grid["xs"][:-1], grid["xs"][1:], strict=True):
        selected = [
            index
            for index, token in enumerate(tokens)
            if x0 <= token["x"] < x1 and grid["ys"][0] <= token["y"] < grid["ys"][1]
        ]
        if not selected:
            raise AssertionError("Controlled original caption has no page observation")
        tokens[selected[0]]["text"] = hint
        remove.update(selected[1:])
    tokens[:] = [token for index, token in enumerate(tokens) if index not in remove]
    return tokens


class CaptionNominationFormTests(unittest.TestCase):
    def test_an_unparsed_hint_is_not_a_proved_bare_identifier(self):
        grid = {"xs": [20, 180], "ys": [90, 115, 200]}
        tokens = [{"x": 90, "y": 101, "text": "Unresolved"}]
        rows, _ = caption_rows(
            grid,
            tokens,
            [(40, 130, 160, 180)],
            {"role": "unknown", "table_key": "TABLE61"},
        )
        self.assertFalse(rows[0][0][3])

    def execute(self, title, prefixed, hint):
        document, structures, boxes = raster_catalog(title, prefixed=prefixed)
        with document:
            page = document[0]
            grids = detect_ruled_table_regions(page, dpi=240)
            tokens = changed_caption_hints(
                page_tokens(page, dpi=200, allow_tesseract=False),
                grids[0],
                hint,
            )
            return bind_caption_grids(
                document,
                structures,
                boxes,
                [1],
                grids_for_page=lambda _page: grids,
                tokens_for_page=lambda _page: tokens,
            )

    def test_original_prefixed_captions_are_reread_without_a_guessed_bare_form(self):
        for hint in ("Unresolved", "Compounds"):
            with self.subTest(hint=hint):
                result = self.execute("Table 47. Structures", True, hint)
                self.assertEqual(
                    [pair["label"] for pair in result.bindings],
                    ["I-004A", "I-009B"],
                    result.issues,
                )
                self.assertEqual(result.issues, [])
                for pair in result.bindings:
                    self.assertNotIn("identifier_form", pair["ownership"])
                    packet = json.loads(json.dumps(formal_binding(pair)))
                    self.assertTrue(valid_caption_binding_evidence(packet))
                    packet["exact_caption_evidence"]["observations"] = [
                        observation
                        for observation in packet["exact_caption_evidence"][
                            "observations"
                        ]
                        if observation["method"] != "cell_ocr_400dpi"
                    ]
                    self.assertFalse(valid_caption_binding_evidence(packet))

    def test_bare_originals_still_need_a_proved_compound_catalogue_role(self):
        result = self.execute("Table 47. Structures", False, "Unresolved")
        self.assertEqual(result.bindings, [])
        self.assertTrue(result.issues)

    def test_proved_compound_catalogue_can_still_reread_its_original_bare_ids(self):
        result = self.execute("Table 47. Compounds", False, "Unresolved")
        self.assertEqual(
            [pair["label"] for pair in result.bindings],
            ["I-004A", "I-009B"],
            result.issues,
        )
        self.assertEqual(result.issues, [])

    def test_complete_conflicting_identifier_nonfinal_role_or_prose_is_not_a_hint(self):
        for hint in (
            "Compound I-099Z",
            "Intermediate I-004A",
            "Compound I-004A prepared from Compound I-099Z",
        ):
            with self.subTest(hint=hint):
                result = self.execute("Table 47. Structures", True, hint)
                self.assertEqual(result.bindings, [])
                self.assertTrue(result.issues)


if __name__ == "__main__":
    unittest.main()
