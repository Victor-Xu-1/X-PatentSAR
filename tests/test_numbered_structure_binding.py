from __future__ import annotations

import unittest
from copy import deepcopy
from dataclasses import replace

from patent_sar_extractor.core.numbered_structure_binding import (
    NumberedTableCell,
    pair_numbered_table_cells,
)
from patent_sar_extractor.core.pipeline_rules import annotate_binding_accuracy
from patent_sar_extractor.core.structure_catalogs import Catalog


def cell(label: str, row: int, pair: int = 0, *, page: int = 9, confirmed=True):
    x0 = 40.0 + pair * 230
    y0 = 100.0 + row * 100
    return NumberedTableCell(
        page_index=page,
        grid_index=0,
        row=row,
        pair=pair,
        label=label,
        label_bounds=(x0, y0, x0 + 50, y0 + 100),
        structure_bounds=(x0 + 50, y0, x0 + 230, y0 + 100),
        observations=({"method": "native_cell", "text": f"{label}."},),
        label_confirmed=confirmed,
    )


def structure(label_cell, *, name="S1"):
    x0, y0, x1, y1 = label_cell.structure_bounds
    return {
        "id": name,
        "idx": 0,
        "page_no": label_cell.page_index + 1,
        "x0": x0 + 10,
        "y0": y0 + 5,
        "x1": x1 - 10,
        "y1": y1 - 5,
        "image_path": f"/outside-source/{name}.png",
    }


class NumberedStructureBindingTests(unittest.TestCase):
    def test_explicit_selected_reprint_uses_full_catalog_without_false_duplicate(self):
        primary = replace(
            cell("31", 0), catalog=Catalog("Table A", "Complete compounds", False)
        )
        selected = replace(
            cell("31", 0, page=10),
            catalog=Catalog("Table B", "Selected compounds", True),
        )
        result = self._pair(
            [primary, selected],
            [structure(primary, name="primary"), structure(selected, name="reprint")],
        )
        self.assertEqual(
            [(b.label, b.structure["id"]) for b in result.bindings], [("31", "primary")]
        )

    def test_two_full_catalogs_and_novel_selected_ids_remain_competing_evidence(self):
        primary = replace(
            cell("31", 0), catalog=Catalog("Table A", "Complete compounds", False)
        )
        other = replace(
            cell("31", 0, page=10),
            catalog=Catalog("Table B", "Other complete compounds", False),
        )
        self.assertFalse(
            self._pair(
                [primary, other],
                [structure(primary, name="one"), structure(other, name="two")],
            ).bindings
        )
        selected = replace(
            other, catalog=Catalog("Table C", "Selected compounds", True)
        )
        novel = replace(cell("32", 1, page=10), catalog=selected.catalog)
        result = self._pair(
            [primary, selected, novel],
            [
                structure(primary, name="one"),
                structure(selected, name="two"),
                structure(novel, name="novel"),
            ],
        )
        self.assertEqual([b.label for b in result.bindings], ["32"])

    def _pair(self, cells, structures, active=None):
        return pair_numbered_table_cells(
            cells, structures, active or {c.label for c in cells}, recognized_pages={9}
        )

    def test_two_column_pairs_bind_by_cells_not_segment_order(self):
        cells = [cell("1", 0), cell("2", 0, 1), cell("3", 1), cell("4", 1, 1)]
        structures = [structure(c, name=f"S{c.label}") for c in cells]
        original = deepcopy((cells, structures))
        result = self._pair(cells, list(reversed(structures)))
        self.assertEqual(
            [(b.label, b.structure["id"]) for b in result.bindings],
            [("1", "S1"), ("2", "S2"), ("3", "S3"), ("4", "S4")],
        )
        self.assertEqual((cells, structures), original)

    def test_missing_segment_does_not_shift_any_other_id(self):
        cells = [cell("1", 0), cell("2", 0, 1), cell("3", 1), cell("4", 1, 1)]
        structures = [structure(c, name=f"S{c.label}") for c in cells if c.label != "2"]
        result = self._pair(cells, structures)
        self.assertEqual([b.label for b in result.bindings], ["1", "3", "4"])
        self.assertTrue(
            any(i.label == "2" and i.reason == "missing_segment" for i in result.issues)
        )

    def test_missing_or_unverified_cell_label_is_not_inferred(self):
        cells = [cell("1", 0), cell("", 1, confirmed=False), cell("3", 2)]
        structures = [structure(c, name=f"S{i}") for i, c in enumerate(cells)]
        result = self._pair(cells, structures, {"1", "2", "3"})
        self.assertEqual([b.label for b in result.bindings], ["1", "3"])
        self.assertNotIn("2", result.observed_keys)

    def test_duplicate_printed_id_with_unsegmented_rival_is_withheld(self):
        cells = [cell("1", 0), cell("2", 1), cell("2", 2)]
        result = self._pair(
            cells, [structure(c, name=f"S{i}") for i, c in enumerate(cells[:2])]
        )
        self.assertEqual([b.label for b in result.bindings], ["1"])
        self.assertTrue(any(i.reason == "duplicate_label" for i in result.issues))

    def test_more_than_one_segment_in_cell_is_ambiguous(self):
        c = cell("11", 0)
        result = self._pair([c], [structure(c), structure(c, name="RIVAL")])
        self.assertEqual(result.bindings, ())
        self.assertEqual(result.issues[0].reason, "ambiguous_segments")

    def test_segment_crossing_grid_boundary_is_not_owned(self):
        c = cell("11", 0)
        segment = structure(c)
        segment["x0"] = c.structure_bounds[0] - 0.5
        result = self._pair([c], [segment])
        self.assertEqual(result.bindings, ())
        self.assertTrue(
            any(i.reason == "boundary_crossing_segment" for i in result.issues)
        )

    def test_number_suffix_is_preserved_and_parent_is_not_reused(self):
        cells = [cell("8", 0), cell("8A", 1), cell("8B", 2)]
        result = self._pair(
            cells, [structure(c, name=f"S{c.label}") for c in cells], {"8A", "8B"}
        )
        self.assertEqual([b.label for b in result.bindings], ["8A", "8B"])
        parent_only = self._pair(cells[:1], [structure(cells[0])], {"8A", "8B"})
        self.assertEqual(parent_only.bindings, ())

    def test_invalid_geometry_never_creates_a_binding(self):
        c = cell("11", 0)
        for changes in ({"x1": float("nan")}, {"y0": -1}, {"y1": 50}, {"x0": None}):
            with self.subTest(changes=changes):
                result = self._pair([c], [{**structure(c), **changes}])
                self.assertEqual(result.bindings, ())

    def test_invalid_geometry_rival_cannot_be_silently_ignored(self):
        c = cell("11", 0)
        result = self._pair(
            [c], [structure(c), {**structure(c, name="RIVAL"), "y1": float("nan")}]
        )
        self.assertEqual(result.bindings, ())
        self.assertTrue(
            any(i.reason == "invalid_segment_geometry" for i in result.issues)
        )

    def test_overlapping_cells_cannot_own_one_segment_twice(self):
        from dataclasses import replace

        first = cell("11", 0)
        second = replace(
            first, label="12", observations=({"method": "native_cell", "text": "12."},)
        )
        result = self._pair([first, second], [structure(first)])
        self.assertEqual(result.bindings, ())
        self.assertTrue(
            any(i.reason == "ambiguous_cell_ownership" for i in result.issues)
        )

    def test_segment_identity_cannot_be_used_on_two_pages(self):
        cells = [cell("1", 0), cell("2", 0, page=10)]
        result = self._pair(cells, [structure(c) for c in cells])
        self.assertEqual(result.bindings, ())
        self.assertTrue(
            any(i.reason == "duplicate_structure_id" for i in result.issues)
        )

    def test_scanned_id_needs_independent_agreeing_observations(self):
        from dataclasses import replace

        c = replace(
            cell("11", 0),
            observations=(
                {"method": "page_ocr_cell", "text": "11."},
                {"method": "cell_ocr_400dpi", "text": "11", "confidence": 0.94},
            ),
        )
        self.assertEqual(len(self._pair([c], [structure(c)]).bindings), 1)
        wrong = replace(
            c,
            observations=(
                {"method": "page_ocr_cell", "text": "11."},
                {"method": "cell_ocr_400dpi", "text": "17", "confidence": 0.94},
            ),
        )
        self.assertEqual(self._pair([wrong], [structure(wrong)]).bindings, ())

    def test_empty_recognized_grid_does_not_fall_back_to_global_zip(self):
        from patent_sar_extractor.core.structure_binder import (
            _extract_authoritative_structure_table_sequence_bindings,
        )

        c = cell("1", 0)
        result = self._pair([], [structure(c)], {"1"})
        self.assertTrue(result.recognized)
        bindings = _extract_authoritative_structure_table_sequence_bindings(
            [structure(c)],
            {9: "\n".join(f"Compound {n}" for n in range(1, 7))},
            [f"Compound {n}" for n in range(1, 7)],
            {"authoritative_structure_table_pages": [9]},
            numbered_result=result,
        )
        self.assertEqual(bindings, [])

    def test_strict_accuracy_accepts_validated_cell_evidence_only(self):
        from patent_sar_extractor.core.structure_binder import (
            _extract_authoritative_structure_table_sequence_bindings,
        )

        c = cell("11", 0)
        result = self._pair([c], [structure(c)])
        binding = _extract_authoritative_structure_table_sequence_bindings(
            [structure(c)],
            {},
            ["Compound 11"],
            {"authoritative_structure_table_pages": [9]},
            numbered_result=result,
        )[0]
        annotated = annotate_binding_accuracy(binding)
        self.assertEqual(annotated["accuracy_status"], "confirmed")
        self.assertFalse(annotated["fail_closed"])
        self.assertEqual(binding["binding_rule"], "numbered_structure_table_cell")
        self.assertEqual(
            binding["numbered_table_cell_evidence"]["label_bbox"], list(c.label_bounds)
        )
        for changes in (
            {"numbered_table_cell_evidence": {}},
            {"compound_id": "Compound 11A"},
            {"page_no": 9},
            {"struct_x0": 0.0},
            {
                "numbered_table_cell_evidence": {
                    **binding["numbered_table_cell_evidence"],
                    "contained_segment_count": True,
                }
            },
            {
                "numbered_table_cell_evidence": {
                    **binding["numbered_table_cell_evidence"],
                    "label_bbox": "1234",
                }
            },
        ):
            with self.subTest(changes=changes):
                invalid = annotate_binding_accuracy({**binding, **changes})
                self.assertEqual(invalid["accuracy_status"], "review_required")
                self.assertTrue(invalid["fail_closed"])

    def test_strict_visible_conflict_is_not_waived_by_cell_binding(self):
        from patent_sar_extractor.core.structure_binder import (
            _extract_authoritative_structure_table_sequence_bindings,
        )

        c = cell("11", 0)
        result = self._pair([c], [structure(c)])
        binding = _extract_authoritative_structure_table_sequence_bindings(
            [structure(c)],
            {},
            ["Compound 11"],
            {"authoritative_structure_table_pages": [9]},
            numbered_result=result,
        )[0]
        binding["visible_label_candidates"] = [{"label": "12", "source": "pdf_clip"}]
        self.assertEqual(
            annotate_binding_accuracy(binding)["evidence_tier"], "conflict"
        )


class NumberedTableObservationTests(unittest.TestCase):
    def _page(self, labels, *, header=True):
        from types import SimpleNamespace

        xs = [40.0, 90.0, 270.0]
        ys = [80.0, 100.0, 200.0, 300.0] if header else [80.0, 180.0, 280.0]
        tokens = []
        if header:
            tokens = [
                {"text": "Cmpd No.", "x": 65.0, "y": 90.0},
                {"text": "Structure", "x": 180.0, "y": 90.0},
            ]
        for index, label in enumerate(labels, start=int(header)):
            tokens.append(
                {"text": label, "x": 65.0, "y": (ys[index] + ys[index + 1]) / 2}
            )
        return SimpleNamespace(
            tokens=tokens,
            grids=[{"xs": xs, "ys": ys}],
            get_text=lambda mode: ["native"],
        )

    def _observe(self, pages, indices, active):
        from types import SimpleNamespace

        from patent_sar_extractor.core.numbered_structure_binding import (
            bind_numbered_tables,
        )

        calls = []

        def reader(page, bounds, tokens, kind, native):
            self.assertEqual(kind, "id")
            self.assertTrue(native)
            values = [
                t["text"]
                for t in tokens
                if bounds[0] < t["x"] < bounds[2] and bounds[1] < t["y"] < bounds[3]
            ]
            text = " ".join(values)
            return SimpleNamespace(
                value=text.removesuffix("."),
                needs_review=False,
                observations=[{"method": "native_cell", "text": text}],
            )

        result = bind_numbered_tables(
            pages,
            [],
            indices,
            active,
            grids_for_page=lambda page: page.grids,
            tokens_for_page=lambda page: calls.append(page) or page.tokens,
            cell_reader=reader,
        )
        return result, calls

    def test_adjacent_continuation_reuses_geometry_not_global_id_sequence(self):
        pages = [self._page(["1.", "2."]), self._page(["31A.", "31B."], header=False)]
        result, calls = self._observe(pages, [0, 1], {"1", "2", "31A", "31B"})
        self.assertEqual(result.recognized_pages, (0, 1))
        self.assertEqual(result.observed_keys, frozenset({"1", "2", "31A", "31B"}))
        self.assertEqual(len(calls), 2)

    def test_missing_page_cannot_prove_a_headerless_continuation(self):
        pages = [
            self._page(["1.", "2."]),
            self._page(["8.", "9."], header=False),
            self._page(["31.", "32."], header=False),
        ]
        result, _ = self._observe(pages, [0, 2], {"1", "2", "31", "32"})
        self.assertEqual(result.recognized_pages, (0,))
        self.assertNotIn("31", result.observed_keys)

    def test_no_grid_does_not_start_coordinate_ocr(self):
        page = self._page(["1.", "2."])
        page.grids = []
        result, calls = self._observe([page], [0], {"1", "2"})
        self.assertFalse(result.recognized)
        self.assertEqual(calls, [])

    def test_series_labels_remain_owned_by_existing_series_rule(self):
        page = self._page(["I-1", "I-2"])
        result, _ = self._observe([page], [0], {"1", "2"})
        self.assertFalse(result.recognized)

    def test_header_without_readable_ids_still_blocks_global_zip(self):
        page = self._page(["unreadable", "unreadable"])
        result, _ = self._observe([page], [0], {"1", "2"})
        self.assertTrue(result.recognized)
        self.assertEqual(result.bindings, ())
        self.assertEqual(result.observed_keys, frozenset())


if __name__ == "__main__":
    unittest.main()
