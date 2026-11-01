"""Original caption layout is not conditional on complete detector recall."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import fitz

from patent_sar_extractor.artifact_io import load_json
from patent_sar_extractor.core.caption_binding_proof import (
    valid_caption_binding_evidence,
)
from patent_sar_extractor.core.caption_grid_binding import bind_caption_grids
from patent_sar_extractor.core.formal_structure import coverage_errors
from patent_sar_extractor.core.structure_binder import bind
from patent_sar_extractor.core.unruled_structure_observation import (
    observe_unruled_tables,
)
from tests.test_caption_role_continuation import binding


def original_grid(
    *, missing_drawing=False, unread_caption=False, ambiguous_drawing=False, columns=2
):
    """Native text and vector ink; no private PDF or recognizer predictions."""
    document = fitz.open()
    page = document.new_page()
    xs, ys = [50 + 130 * index for index in range(columns + 1)], [100, 125, 205]
    page.insert_text((50, 85), "Table 47. Structures", fontsize=10)
    for x in xs:
        page.draw_line((x, ys[0]), (x, ys[-1]))
    for y in ys:
        page.draw_line((xs[0], y), (xs[-1], y))
    structures, boxes = [], []
    for column, label in enumerate(("41A", "89B", "7E", "8E")[:columns]):
        text = "Compound ?" if unread_caption and column == 1 else "Compound " + label
        page.insert_text((xs[column] + 12, 117), text, fontsize=8)
        box = [xs[column] + 20, 145, xs[column] + 80, 180]
        page.draw_polyline([(box[0], 170), ((box[0] + box[2]) / 2, 145), (box[2], 170)])
        if not (missing_drawing and column == 1):
            structures.append(
                {
                    "id": f"generated-{column}",
                    "page_no": 1,
                    **dict(zip(("x0", "y0", "x1", "y1"), box, strict=True)),
                }
            )
            boxes.append(box)
            if ambiguous_drawing and column == 1:
                structures.append({**structures[-1], "id": "generated-overlap"})
                boxes.append(list(box))
    return document, {1: structures}, {1: boxes}, [{"xs": xs, "ys": ys}]


def observations(**options):
    document, structures, boxes, grids = original_grid(**options)
    with document:
        captions = bind_caption_grids(
            document,
            structures,
            boxes,
            [1],
            grids_for_page=lambda _page: grids,
        )
        columns = observe_unruled_tables(
            document,
            structures[1],
            [0],
            lambda _page: grids,
            lambda _page: captions.tokens[1],
            page_texts=[document[0].get_text()],
            caption_roles=captions.roles,
            caption_frames=captions.frames,
        )
        return captions, columns


class CaptionFrameInventoryTests(unittest.TestCase):
    def assert_original_pairs(self, captions, expected):
        self.assertEqual(len(captions.bindings), expected, captions.issues)
        self.assertTrue(
            all(
                valid_caption_binding_evidence(binding(pair))
                for pair in captions.bindings
            )
        )

    def test_complete_prefixed_caption_inventory_keeps_its_original_layout(self):
        captions, columns = observations()
        self.assert_original_pairs(captions, 2)
        self.assertEqual(captions.issues, [])
        self.assertEqual([section["role"] for section in columns[1]], [])

    def test_missing_candidate_keeps_caption_failure_without_competing_columns(self):
        captions, columns = observations(missing_drawing=True)
        self.assert_original_pairs(captions, 1)
        self.assertIn(
            "missing_caption_structure", [item["reason"] for item in captions.issues]
        )
        self.assertEqual(
            [section["role"] for section in columns[1]],
            [],
            "Complete original prefixed caption cells retain their layout even "
            "when a drawing candidate is missing; the missing association must "
            "stay failed in that same caption inventory",
        )

    def test_unread_original_caption_cannot_supply_complete_layout_permission(self):
        captions, columns = observations(unread_caption=True)
        self.assert_original_pairs(captions, 1)
        self.assertIn(
            "unread_or_conflicting_caption",
            [item["reason"] for item in captions.issues],
        )
        self.assertTrue(columns[1], "Unproved source cells must not disappear")

    def test_missing_middle_candidate_in_three_columns_never_shifts_other_ids(self):
        captions, columns = observations(missing_drawing=True, columns=3)
        self.assert_original_pairs(captions, 2)
        self.assertEqual({pair["label"] for pair in captions.bindings}, {"41A", "7E"})
        self.assertIn(
            "missing_caption_structure", [item["reason"] for item in captions.issues]
        )
        self.assertEqual([section["role"] for section in columns[1]], [])

    def test_ambiguous_drawing_keeps_layout_but_cannot_grant_an_association(self):
        captions, columns = observations(ambiguous_drawing=True)
        self.assert_original_pairs(captions, 1)
        self.assertEqual(captions.bindings[0]["label"], "41A")
        self.assertIn(
            "ambiguous_caption_structure", [item["reason"] for item in captions.issues]
        )
        self.assertEqual([section["role"] for section in columns[1]], [])

    def test_headerless_columns_cannot_start_a_competing_caption_title_read(self):
        with fitz.open() as document:
            page = document.new_page()
            xs, ys = [50, 180, 310], [100, 205, 310]
            for x in xs:
                page.draw_line((x, ys[0]), (x, ys[-1]))
            for y in ys:
                page.draw_line((xs[0], y), (xs[-1], y))
            structures, boxes = [], []
            for row, label in enumerate(("41A", "89B")):
                top = ys[row]
                page.insert_text((65, top + 40), label, fontsize=9)
                box = [200, top + 25, 260, top + 80]
                page.draw_polyline([(200, top + 70), (230, top + 25), (260, top + 70)])
                boxes.append(box)
                structures.append(
                    {
                        "id": f"generated-column-{row}",
                        "page_no": 1,
                        **dict(zip(("x0", "y0", "x1", "y1"), box, strict=True)),
                    }
                )
            with patch(
                "patent_sar_extractor.core.caption_grid_binding.observe_caption_role",
                side_effect=AssertionError("A column frame is not a caption nominee"),
            ):
                result = bind_caption_grids(
                    document,
                    {1: structures},
                    {1: boxes},
                    [1],
                    grids_for_page=lambda _page: [{"xs": xs, "ys": ys}],
                )
            self.assertEqual(result.roles, {})
            self.assertEqual(result.frames, {})
            self.assertEqual(result.bindings, [])
            self.assertIn(1, result.tokens)

    def test_real_binder_retains_missing_source_and_failed_coverage(self):
        with tempfile.TemporaryDirectory(prefix="caption-source-inventory-") as name:
            root = Path(name)
            original, metadata = root / "original.pdf", root / "structures.json"
            document, structures, _boxes, _grids = original_grid(missing_drawing=True)
            records = []
            with document:
                for index, item in enumerate(structures[1]):
                    bounds = [item[axis] for axis in ("x0", "y0", "x1", "y1")]
                    image = root / (item["id"] + ".png")
                    document[0].get_pixmap(clip=fitz.Rect(bounds), alpha=False).save(
                        image
                    )
                    records.append(
                        {
                            "structure_id": item["id"],
                            "structure_index": index,
                            "page_no": 1,
                            "bbox_pdf": bounds,
                            "image_path": str(image),
                        }
                    )
                document.save(original)
            before = hashlib.sha256(original.read_bytes()).hexdigest()
            metadata.write_text(
                json.dumps(
                    {"patent_number": "GENERATED-CAPTION", "structures": records}
                )
            )
            result = bind(
                str(original),
                {"structure_candidate_pages": [0]},
                str(root / "bindings"),
                str(metadata),
            )
            payload = load_json(Path(result["output_files"]["json"]), None)
            self.assertTrue(payload["source_issues"])
            self.assertIn(
                "missing_caption_structure",
                [issue["reason"] for issue in payload["source_issues"]],
            )
            self.assertTrue(coverage_errors(payload))
            without_flags = {**payload, "source_issues": []}
            self.assertTrue(coverage_errors(without_flags))
            self.assertNotIn(
                "structure_column_anchor",
                [section["role"] for section in payload["source_sections"]],
            )
            self.assertEqual(hashlib.sha256(original.read_bytes()).hexdigest(), before)


if __name__ == "__main__":
    unittest.main()
